"""Local, read-only web interface: ``offline-rag serve``.

The server listens only on the loopback interface, never writes to the index or to the
documents, and uses nothing but the standard library. Requests whose ``Host`` header is not
the loopback address are refused (protection against DNS rebinding).
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .index import search, search_files

LOOPBACK = "127.0.0.1"
MAX_QUERY_CHARS = 500

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>offline-rag</title>
<style>
  :root { color-scheme: light dark; --bg:#fafaf9; --fg:#1c1917; --muted:#78716c; --card:#fff;
          --line:#e7e5e4; --accent:#2563eb; --mark:#fde68a; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161513; --fg:#f5f5f4; --muted:#a8a29e; --card:#1f1d1b; --line:#33302d;
            --accent:#60a5fa; --mark:#854d0e; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 52rem; margin: 0 auto; padding: 2rem 1rem 4rem; }
  h1 { font-size: 1.25rem; margin: 0 0 .25rem; }
  .sub { color: var(--muted); margin: 0 0 1.5rem; font-size: .9rem; }
  form { display:flex; gap:.5rem; }
  input[type=search] { flex:1; padding:.7rem .9rem; font:inherit; color:inherit; background:var(--card);
         border:1px solid var(--line); border-radius:.5rem; }
  button { padding:.7rem 1.1rem; font:inherit; color:#fff; background:var(--accent); border:0;
           border-radius:.5rem; cursor:pointer; }
  input:focus-visible, button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .tabs { display:flex; gap:1rem; margin:1.25rem 0 .75rem; border-bottom:1px solid var(--line); }
  .tabs button { background:none; color:var(--muted); padding:.4rem 0; border-radius:0;
                 border-bottom:2px solid transparent; }
  .tabs button[aria-selected=true] { color:var(--fg); border-bottom-color:var(--accent); }
  #status { color:var(--muted); font-size:.9rem; margin:.5rem 0; }
  ol { list-style:none; padding:0; margin:0; display:grid; gap:.75rem; }
  li { background:var(--card); border:1px solid var(--line); border-radius:.6rem; padding:.8rem 1rem; }
  .where { font-size:.85rem; color:var(--muted); margin-bottom:.3rem; word-break:break-all; }
  .where b { color:var(--fg); font-weight:600; }
  mark { background:var(--mark); color:inherit; border-radius:.2rem; padding:0 .1rem; }
  p { margin:0; }
</style>
</head>
<body>
<main>
  <h1>offline-rag</h1>
  <p class="sub">Searching your local index. Nothing leaves this computer.</p>
  <form id="form" role="search">
    <input id="q" type="search" placeholder="Search your documents" aria-label="Search" autofocus
           autocomplete="off" maxlength="500">
    <button type="submit">Search</button>
  </form>
  <div class="tabs" role="tablist">
    <button type="button" role="tab" id="tab-passages" aria-selected="true">Passages</button>
    <button type="button" role="tab" id="tab-files" aria-selected="false">Files</button>
  </div>
  <div id="status" role="status" aria-live="polite"></div>
  <ol id="results"></ol>
</main>
<script>
"use strict";
const form = document.getElementById("form"), box = document.getElementById("q");
const list = document.getElementById("results"), status = document.getElementById("status");
const tabs = { passages: document.getElementById("tab-passages"), files: document.getElementById("tab-files") };
let view = "passages";

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
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

async function run() {
  const q = box.value.trim();
  const url = new URL(location.href);
  url.searchParams.set("q", q); url.searchParams.set("view", view);
  history.replaceState(null, "", url);
  if (!q) return show("");
  status.textContent = "Searching…";
  let data;
  try {
    const response = await fetch("/api/" + (view === "files" ? "files" : "search") + "?q=" + encodeURIComponent(q));
    data = await response.json();
    if (!response.ok) return show(data.error || "Search failed.");
  } catch (error) { return show("Could not reach the local server."); }
  list.replaceChildren();
  if (view === "files") {
    status.textContent = data.total ? data.total + (data.total === 1 ? " file" : " files")
      + (data.match === "any" ? " (no file contains every word; showing files with at least one)" : "")
      : "No files found.";
    data.files.forEach(f => {
      const item = el("li");
      item.appendChild(el("div", f.path, "where"));
      item.appendChild(el("p", f.matches + (f.matches === 1 ? " matching passage" : " matching passages")
        + (f.pages.length ? " · pages " + f.pages.join(", ") : "")));
      list.appendChild(item);
    });
  } else {
    status.textContent = data.results.length ? "" : "No matching passages found.";
    data.results.forEach(r => {
      const item = el("li"), where = el("div", undefined, "where");
      where.appendChild(el("b", r.path));
      if (r.page) where.appendChild(document.createTextNode(" · page " + r.page));
      item.appendChild(where);
      item.appendChild(snippetNode(r.snippet));
      list.appendChild(item);
    });
  }
}
function select(next) {
  view = next;
  for (const [name, tab] of Object.entries(tabs)) tab.setAttribute("aria-selected", String(name === next));
  run();
}
tabs.passages.addEventListener("click", () => select("passages"));
tabs.files.addEventListener("click", () => select("files"));
form.addEventListener("submit", event => { event.preventDefault(); run(); });
const params = new URLSearchParams(location.search);
if (params.get("q")) { box.value = params.get("q"); select(params.get("view") === "files" ? "files" : "passages"); }
</script>
</body>
</html>
"""

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


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
