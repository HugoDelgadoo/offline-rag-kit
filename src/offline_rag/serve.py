"""Local, read-only web interface: ``offline-rag serve``.

The server listens only on the loopback interface, never writes to the index or to the
documents, and uses nothing but the standard library. Requests whose ``Host`` header is not
the loopback address are refused (protection against DNS rebinding).
"""

import json
import sqlite3
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pymupdf

from .index import search, search_files

LOOPBACK = "127.0.0.1"
MAX_QUERY_CHARS = 500
MAX_PREVIEW_PIXELS = 1600  # width of the rendered page image
HIGHLIGHT_FILL = (1.0, 0.85, 0.0)
CONTEXT_POINTS = 110  # page context shown above and below the passage (PDF points)

_render_lock = threading.Lock()  # PyMuPDF is not thread-safe

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#fafaf9" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#161513" media="(prefers-color-scheme: dark)">
<title>offline-rag</title>
<style>
  :root { color-scheme: light dark; --bg:#fafaf9; --fg:#1c1917; --muted:#6b645f; --card:#fff;
          --line:#e7e5e4; --accent:#2563eb; --accent-hover:#1d4ed8; --mark:#fde68a; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161513; --fg:#f5f5f4; --muted:#a8a29e; --card:#1f1d1b; --line:#33302d;
            --accent:#60a5fa; --accent-hover:#93c5fd; --mark:#854d0e; } }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 52rem; margin: 0 auto; padding: 2rem 1rem 4rem; }
  h1 { font-size: 1.25rem; margin: 0 0 .25rem; text-wrap: balance; }
  .sub { color: var(--muted); margin: 0 0 1.5rem; font-size: .9rem; }
  .sr-only { position:absolute; width:1px; height:1px; margin:-1px; padding:0; overflow:hidden;
             clip:rect(0 0 0 0); white-space:nowrap; border:0; }
  button, input { touch-action: manipulation; -webkit-tap-highlight-color: transparent; }
  button { font:inherit; cursor:pointer; transition: background-color .15s, color .15s, border-color .15s; }
  @media (prefers-reduced-motion: reduce) { button { transition: none; } }
  form { display:flex; gap:.5rem; }
  input[type=search] { flex:1; min-width:0; padding:.7rem .9rem; font:inherit; color:inherit;
         background:var(--card); border:1px solid var(--line); border-radius:.5rem; }
  .primary { padding:.7rem 1.1rem; color:#fff; background:var(--accent); border:0; border-radius:.5rem; }
  .primary:hover { background:var(--accent-hover); }
  @media (prefers-color-scheme: dark) { .primary { color:#0b1220; } }
  input:focus-visible, button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .views { display:flex; gap:1rem; margin:1.25rem 0 .75rem; border-bottom:1px solid var(--line); }
  .views button { background:none; color:var(--muted); border:0; border-bottom:2px solid transparent;
                  border-radius:0; padding:.4rem 0; }
  .views button:hover { color:var(--fg); }
  .views button[aria-pressed=true] { color:var(--fg); border-bottom-color:var(--accent); }
  #status { color:var(--muted); font-size:.9rem; margin:.5rem 0; font-variant-numeric: tabular-nums; }
  ol { list-style:none; padding:0; margin:0; display:grid; gap:.75rem; }
  li { background:var(--card); border:1px solid var(--line); border-radius:.6rem; padding:.8rem 1rem;
       min-width:0; }
  .where { font-size:.85rem; color:var(--muted); margin-bottom:.3rem; overflow-wrap:anywhere; }
  .where b { color:var(--fg); font-weight:600; }
  .fname { font-weight:600; overflow-wrap:anywhere; }
  .dir { font-size:.8rem; color:var(--muted); overflow-wrap:anywhere; margin-bottom:.3rem; }
  mark { background:var(--mark); color:inherit; border-radius:.2rem; padding:0 .1rem; }
  p { margin:0; overflow-wrap:anywhere; }
  .small { font-size:.9rem; color:var(--muted); font-variant-numeric: tabular-nums; }
  .actions { display:flex; flex-wrap:wrap; gap:.5rem; margin-top:.6rem; }
  .ghost { padding:.3rem .75rem; font-size:.85rem; color:var(--accent); background:transparent;
           border:1px solid var(--line); border-radius:.4rem; }
  .ghost:hover { border-color:var(--accent); color:var(--accent-hover); }
  img.preview { display:block; width:100%; height:auto; margin-top:.6rem; background:#fff;
                border:1px solid var(--line); border-radius:.4rem; }
  .err { color:var(--muted); font-size:.9rem; margin-top:.5rem; }
</style>
</head>
<body>
<main>
  <h1>offline-rag</h1>
  <p class="sub">Search your local index. Nothing leaves this computer.</p>
  <form id="form" role="search">
    <label class="sr-only" for="q">Search your documents</label>
    <input id="q" name="q" type="search" placeholder="Try “retention policy”…" autocomplete="off"
           autocapitalize="off" spellcheck="false" enterkeyhint="search" maxlength="500">
    <button class="primary" type="submit">Search</button>
  </form>
  <div class="views" role="group" aria-label="Result view">
    <button type="button" id="view-passages" aria-pressed="true">Passages</button>
    <button type="button" id="view-files" aria-pressed="false">Files</button>
  </div>
  <div id="status" role="status" aria-live="polite"></div>
  <ol id="results"></ol>
</main>
<script>
"use strict";
const form = document.getElementById("form"), box = document.getElementById("q");
const list = document.getElementById("results"), status = document.getElementById("status");
const views = { passages: document.getElementById("view-passages"), files: document.getElementById("view-files") };
const NBSP = " ";
let view = "passages";

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
const plural = (n, one, many) => n + NBSP + (n === 1 ? one : many);

// The snippet marks matches with **...**; build DOM nodes instead of HTML so that
// document text can never be interpreted as markup.
function snippetNode(snippet) {
  const p = el("p");
  snippet.split("**").forEach((part, i) => {
    if (i % 2) p.appendChild(el("mark", part)); else p.appendChild(document.createTextNode(part));
  });
  return p;
}
function show(message) { status.textContent = message; list.replaceChildren(); }

// "Show Page" loads /preview?id=N: a band of the PDF page around the passage, highlighted.
// "Show Full Page" loads the whole page.
function previewControl(r) {
  const wrap = el("div", undefined, "actions");
  const toggle = el("button", "Show Page" + NBSP + r.page, "ghost");
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", "false");
  let image = null, note = null, fullButton = null, full = false;

  function load() {
    image.className = "preview";
    image.style.aspectRatio = full ? "auto 1 / 1.414" : "auto 3 / 1";
    image.alt = "Page " + r.page + " of " + r.path + (full ? "" : ", around the passage") + ", passage highlighted";
    image.src = "/preview?id=" + encodeURIComponent(r.id) + (full ? "&full=1" : "");
  }
  function close() {
    if (image) image.remove();
    if (note) note.remove();
    if (fullButton) fullButton.remove();
    image = note = fullButton = null; full = false;
    toggle.textContent = "Show Page" + NBSP + r.page;
    toggle.setAttribute("aria-expanded", "false");
  }
  toggle.addEventListener("click", () => {
    if (image || note) return close();
    image = document.createElement("img");
    image.addEventListener("error", () => {
      if (!image) return;
      note = el("p", "Preview unavailable. The file may have moved or changed: run “offline-rag ingest” again.", "err");
      image.remove(); image = null;
      if (fullButton) { fullButton.remove(); fullButton = null; }
      wrap.parentNode.appendChild(note);
    });
    load();
    fullButton = el("button", "Show Full Page", "ghost");
    fullButton.type = "button";
    fullButton.addEventListener("click", () => {
      full = !full;
      fullButton.textContent = full ? "Show Passage Only" : "Show Full Page";
      load();
    });
    wrap.appendChild(fullButton);
    wrap.parentNode.appendChild(image);
    toggle.textContent = "Hide Page";
    toggle.setAttribute("aria-expanded", "true");
  });
  wrap.appendChild(toggle);
  return wrap;
}

function fileNode(f) {
  const item = el("li");
  const name = f.relative_path.split(/[\\/]/).pop();
  const dir = f.path.slice(0, f.path.length - name.length).replace(/[\\/]+$/, "");
  item.appendChild(el("div", name, "fname"));
  item.appendChild(el("div", dir, "dir"));
  item.appendChild(el("p", plural(f.matches, "matching passage", "matching passages")
    + (f.pages.length ? " · Pages" + NBSP + f.pages.join(", ") : ""), "small"));
  return item;
}

function passageNode(r) {
  const item = el("li"), where = el("div", undefined, "where");
  const name = el("b", r.path);
  name.translate = false;
  where.appendChild(name);
  if (r.page) where.appendChild(document.createTextNode(" · Page" + NBSP + r.page));
  item.appendChild(where);
  item.appendChild(snippetNode(r.snippet));
  if (r.page) item.appendChild(previewControl(r));
  return item;
}

async function run() {
  const q = box.value.trim();
  const url = new URL(location.href);
  if (q) { url.searchParams.set("q", q); url.searchParams.set("view", view); }
  else { url.searchParams.delete("q"); url.searchParams.delete("view"); }
  history.replaceState(null, "", url);
  if (!q) return show("");
  status.textContent = "Searching…";
  let data;
  try {
    const response = await fetch("/api/" + (view === "files" ? "files" : "search") + "?q=" + encodeURIComponent(q));
    data = await response.json();
    if (!response.ok) return show((data.error || "Search failed.") + " Check your words and try again.");
  } catch (error) {
    return show("Could not reach the local server. Check that “offline-rag serve” is still running.");
  }
  list.replaceChildren();
  if (view === "files") {
    if (!data.files.length) return show("No files found. Try fewer or different words.");
    status.textContent = data.total > data.files.length
      ? "Showing the best " + data.files.length + " of " + plural(data.total, "file", "files")
      : plural(data.total, "file", "files")
        + (data.match === "any" ? " (none contains every word; showing files with at least one)" : "");
    data.files.forEach(f => list.appendChild(fileNode(f)));
  } else {
    if (!data.results.length) return show("No matching passages found. Try fewer or different words.");
    const n = data.results.length;
    status.textContent = n >= 10 ? "Showing the best " + n + " passages" : plural(n, "passage", "passages");
    data.results.forEach(r => list.appendChild(passageNode(r)));
  }
}
function select(next) {
  view = next;
  for (const [name, button] of Object.entries(views)) button.setAttribute("aria-pressed", String(name === next));
  run();
}
views.passages.addEventListener("click", () => select("passages"));
views.files.addEventListener("click", () => select("files"));
form.addEventListener("submit", event => { event.preventDefault(); run(); });
const params = new URLSearchParams(location.search);
if (params.get("q")) { box.value = params.get("q"); select(params.get("view") === "files" ? "files" : "passages"); }
if (window.matchMedia("(pointer: fine)").matches) box.focus();  // not on touch screens
</script>
</body>
</html>
"""

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class PreviewError(Exception):
    """The preview cannot be produced; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def render_preview(database: str | Path, passage_id: int, full: bool = False) -> bytes:
    """Render the PDF page of an indexed passage as PNG with the passage highlighted.

    By default only a horizontal band around the passage is rendered (with some context above and
    below); ``full=True`` renders the whole page. Rotated pages are always rendered whole.

    The file is found through the index (never through a path sent by the browser), must sit
    inside the folder that was ingested, and is opened read-only and never saved.
    """
    uri = Path(database).expanduser().resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        row = connection.execute(
            "SELECT root, path, page, bbox FROM passages WHERE rowid = ?", (passage_id,)
        ).fetchone()
    if row is None:
        raise PreviewError(404, "Unknown passage.")
    root, relative, page_number, bbox = row
    if not page_number or not relative.lower().endswith(".pdf"):
        raise PreviewError(404, "Only PDF passages have a preview.")
    root_path = Path(root).resolve()
    file = (root_path / relative).resolve()
    if not file.is_relative_to(root_path):
        raise PreviewError(403, "The file is outside the indexed folder.")
    if not file.is_file():
        raise PreviewError(404, "The file is no longer there. Run 'offline-rag ingest' again.")
    try:
        with _render_lock, pymupdf.open(file) as document:
            if not 1 <= int(page_number) <= document.page_count:
                raise PreviewError(404, "The file changed since it was indexed. Run 'offline-rag ingest' again.")
            page = document[int(page_number) - 1]
            clip = page.rect
            if bbox:
                # Stored in the same (unrotated) space PyMuPDF draws in.
                x0, y0, x1, y1 = (float(n) for n in bbox.split(","))
                page.draw_rect(
                    pymupdf.Rect(x0, y0, x1, y1), color=HIGHLIGHT_FILL, fill=HIGHLIGHT_FILL,
                    fill_opacity=0.35, width=1.2,
                )
                if not full and not page.rotation:
                    clip = pymupdf.Rect(
                        page.rect.x0, max(page.rect.y0, y0 - CONTEXT_POINTS),
                        page.rect.x1, min(page.rect.y1, y1 + CONTEXT_POINTS),
                    )
            zoom = min(2.0, MAX_PREVIEW_PIXELS / max(page.rect.width, 1.0))
            return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False).tobytes("png")
    except PreviewError:
        raise
    except (RuntimeError, ValueError) as exc:  # damaged or encrypted PDF, bad stored bbox
        raise PreviewError(422, f"The page could not be rendered: {exc}") from exc


def _hit_payload(hit: dict) -> dict:
    return {
        "id": hit["id"],
        "path": hit["path"],
        "page": hit["page"] or None,
        "bbox": [float(n) for n in hit["bbox"].split(",")] if hit["bbox"] else None,
        "snippet": hit["snippet"],
    }


class _Handler(BaseHTTPRequestHandler):
    server: "LocalServer"
    server_version = "offline-rag"
    sys_version = ""

    def log_message(self, format, *args):  # noqa: A002 - keep the console quiet; never log queries
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _host_allowed(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"{LOOPBACK}:{port}", f"localhost:{port}"}

    def do_GET(self):  # noqa: N802 - http.server API
        if not self._host_allowed():
            return self._json(403, {"error": "Forbidden host."})
        url = urlsplit(self.path)
        if url.path == "/":
            return self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        if url.path in ("/api/search", "/api/files"):
            query = parse_qs(url.query).get("q", [""])[0].strip()
            if not query:
                return self._json(400, {"error": "Missing search terms."})
            if len(query) > MAX_QUERY_CHARS:
                return self._json(400, {"error": f"Query is longer than {MAX_QUERY_CHARS} characters."})
            try:
                if url.path == "/api/search":
                    hits = search(query, self.server.database, 10)
                    return self._json(200, {"query": query, "results": [_hit_payload(h) for h in hits]})
                return self._json(200, {"query": query, **search_files(query, self.server.database, 50)})
            except (OSError, ValueError) as exc:
                return self._json(500, {"error": str(exc)})
        if url.path == "/preview":
            params = parse_qs(url.query)
            raw = params.get("id", [""])[0]
            if not raw.isascii() or not raw.isdigit():
                return self._json(400, {"error": "Missing or invalid passage id."})
            try:
                png = render_preview(self.server.database, int(raw), full=params.get("full", [""])[0] == "1")
            except PreviewError as exc:
                return self._json(exc.status, {"error": str(exc)})
            except (OSError, sqlite3.Error) as exc:
                return self._json(500, {"error": str(exc)})
            return self._send(200, png, "image/png")
        self._json(404, {"error": "Not found."})

    def _method_not_allowed(self):
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_PUT = do_DELETE = do_PATCH = _method_not_allowed  # noqa: N815 - read-only server


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, database: str | Path, port: int = 8765):
        self.database = str(database)
        super().__init__((LOOPBACK, port), _Handler)


def make_server(database: str | Path, port: int = 8765) -> LocalServer:
    """Create the server (bound to 127.0.0.1 only). The index must already exist."""
    if not Path(database).expanduser().is_file():
        raise ValueError(f"No index at {database}. Run 'offline-rag ingest FOLDER' first.")
    return LocalServer(database, port)
