"""SQLite FTS5 search index with PDF page and bounding-box citations."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import pymupdf

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}
# Bump when extraction changes, so files indexed by older versions are re-extracted
# even though their content hash is unchanged. Stored as a prefix of the file hash.
EXTRACTOR_VERSION = 3
_HASH_PREFIX = f"x{EXTRACTOR_VERSION}:"


def open_index(database: str | Path) -> sqlite3.Connection:
    target = Path(database).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    columns = [row[1] for row in connection.execute("PRAGMA table_info(passages)")]
    if columns and "root" not in columns:
        connection.close()
        raise ValueError(
            f"{target} was created by an older version that stored absolute paths. "
            "Delete it and run 'offline-rag ingest' again."
        )
    connection.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
            root UNINDEXED,
            path UNINDEXED,
            page UNINDEXED,
            bbox UNINDEXED,
            body,
            tokenize = 'unicode61 remove_diacritics 2'
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS embeddings (
            passage_rowid INTEGER PRIMARY KEY,
            model TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS files (
            root TEXT NOT NULL, path TEXT NOT NULL,
            size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL,
            PRIMARY KEY (root, path)
        )"""
    )
    return connection


_HYPHEN_BREAK = re.compile(r"(\w)-[ \t]*\n[ \t]*(\w)")


def join_hyphenated(text: str) -> str:
    """Rejoin words split by a hyphen at the end of a line ("docu-\\nment" -> "document").

    The break is removed when the next line continues in lowercase; if it starts with a
    capital or digit ("Jean-\\nPaul") the hyphen is kept. A real compound split at a
    line end ("state-\\nof-the-art") loses its hyphen: an accepted trade-off, because
    unjoined fragments ("docu- ment") cannot be found by search at all.
    """
    def repair(match: re.Match) -> str:
        before, after = match.group(1), match.group(2)
        return before + after if after.islower() else f"{before}-{after}"

    return _HYPHEN_BREAK.sub(repair, text)


def _table_passages(page: "pymupdf.Page") -> list[tuple[pymupdf.Rect, str]]:
    """Return (bbox, text) for each ruled table on the page; never raises."""
    try:
        tables = page.find_tables().tables
    except Exception:  # table detection is best-effort; plain text extraction still works
        return []
    found = []
    for table in tables:
        rows = [
            [" ".join(str(cell or "").split()) for cell in row]
            for row in table.extract()
        ]
        rows = [row for row in rows if any(row)]
        if len(rows) < 2 or max(len(row) for row in rows) < 2:
            continue  # a single row or column is not worth treating as a table
        found.append((pymupdf.Rect(table.bbox), "; ".join(" | ".join(row) for row in rows)))
    return found


def extract_passages(path: Path) -> Iterator[tuple[int, str, str]]:
    """Yield (page number, bounding box, paragraph text). Page 0 means text file.

    Ruled PDF tables are emitted as one passage ("Item | Years; Invoices | 10; ...")
    so a row stays connected to its header; text blocks inside a table are not repeated.
    """
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as document:
            for page_number, page in enumerate(document, start=1):
                tables = _table_passages(page)
                for rect, text in tables:
                    yield page_number, ",".join(f"{n:.1f}" for n in rect), text
                for block in page.get_text("blocks"):
                    if len(block) > 6 and block[6] != 0:
                        continue  # Skip image blocks.
                    body = " ".join(join_hyphenated(str(block[4])).split())
                    if not body:
                        continue
                    centre = pymupdf.Point((block[0] + block[2]) / 2, (block[1] + block[3]) / 2)
                    if any(centre in rect for rect, _ in tables):
                        continue  # already part of a table passage
                    bbox = ",".join(f"{float(n):.1f}" for n in block[:4])
                    yield page_number, bbox, body
    else:
        text = path.read_text(encoding="utf-8-sig")
        for paragraph in re.split(r"\n\s*\n", text):
            body = " ".join(paragraph.split())
            if body:
                yield 0, "", body


@dataclass
class IngestResult:
    """Outcome of :func:`ingest`. ``files``/``passages`` count everything now in the index
    for the folder; ``unchanged`` of those files were skipped because their content did not change."""

    files: int = 0
    passages: int = 0
    unchanged: int = 0
    skipped: list[tuple[Path, Exception]] = field(default_factory=list)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ingest(folder: str | Path, database: str | Path) -> IngestResult:
    """Index all documents recursively and incrementally.

    Files whose content hash is unchanged since the last run are not re-parsed;
    changed files replace their old passages. Files that cannot be read (corrupt or
    encrypted PDFs, non-UTF-8 text) are reported in ``result.skipped`` and keep their
    previous passages, if any. Passages of files that no longer exist under ``folder``
    (or of folders that no longer exist) are removed.
    """
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Folder not found: {root}")
    documents = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    result = IngestResult()
    root_key = str(root)
    with closing(open_index(database)) as connection:
        for path in documents:
            relative = path.relative_to(root).as_posix()
            try:
                stat = path.stat()
                known = connection.execute(
                    "SELECT size, mtime_ns, sha256 FROM files WHERE root = ? AND path = ?",
                    (root_key, relative),
                ).fetchone()
                current = bool(known) and known["sha256"].startswith(_HASH_PREFIX)
                if current and (known["size"], known["mtime_ns"]) == (stat.st_size, stat.st_mtime_ns):
                    digest = known["sha256"]  # same size and mtime: trust it, skip hashing
                else:
                    digest = _HASH_PREFIX + _sha256(path)
                if current and known["sha256"] == digest:
                    count = connection.execute(
                        "SELECT COUNT(*) FROM passages WHERE root = ? AND path = ?", (root_key, relative)
                    ).fetchone()[0]
                    with connection:
                        connection.execute(
                            "UPDATE files SET size = ?, mtime_ns = ? WHERE root = ? AND path = ?",
                            (stat.st_size, stat.st_mtime_ns, root_key, relative),
                        )
                    result.files += 1
                    result.unchanged += 1
                    result.passages += count
                    continue
                entries = list(extract_passages(path))
            except Exception as exc:  # parsers raise many different error types
                result.skipped.append((path, exc))
                continue
            with connection:
                _delete_passages(connection, root_key, relative)
                connection.executemany(
                    "INSERT INTO passages (root, path, page, bbox, body) VALUES (?, ?, ?, ?, ?)",
                    ((root_key, relative, page, bbox, body) for page, bbox, body in entries),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO files (root, path, size, mtime_ns, sha256) VALUES (?, ?, ?, ?, ?)",
                    (root_key, relative, stat.st_size, stat.st_mtime_ns, digest),
                )
            result.files += 1
            result.passages += len(entries)
        _remove_stale(connection, root_key, {p.relative_to(root).as_posix() for p in documents})
    return result


def _delete_passages(connection: sqlite3.Connection, root: str, path: str) -> None:
    """Delete a file's passages together with their embeddings."""
    connection.execute(
        "DELETE FROM embeddings WHERE passage_rowid IN "
        "(SELECT rowid FROM passages WHERE root = ? AND path = ?)",
        (root, path),
    )
    connection.execute("DELETE FROM passages WHERE root = ? AND path = ?", (root, path))


def _remove_stale(connection: sqlite3.Connection, root_key: str, present: set[str]) -> None:
    """Delete data of removed files, and of folders that no longer exist (moved/renamed)."""
    rows = connection.execute(
        "SELECT root, path FROM passages UNION SELECT root, path FROM files"
    ).fetchall()
    stale = [
        (row["root"], row["path"])
        for row in rows
        if (row["root"] == root_key and row["path"] not in present)
        or (row["root"] != root_key and not os.path.isdir(row["root"]))
    ]
    with connection:
        for root_value, path_value in stale:
            _delete_passages(connection, root_value, path_value)
        connection.executemany("DELETE FROM files WHERE root = ? AND path = ?", stale)


def search(query: str, database: str | Path, limit: int = 5) -> list[dict]:
    """Rank passages with BM25, preferring passages that contain every term.

    Passages matching all query terms (AND) come first; if there are fewer than
    ``limit`` of them, the remaining slots are filled with passages matching any
    term (OR), so multi-word queries stay precise without losing recall.
    """
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    tokens = list(dict.fromkeys(re.findall(r"\w+", query, flags=re.UNICODE)))
    if not tokens:
        return []
    # Quoting every user token avoids injecting FTS5 operators or syntax.
    quoted = [f'"{token}"' for token in tokens]
    modes = [" AND ".join(quoted)]
    if len(quoted) > 1:
        modes.append(" OR ".join(quoted))
    results: list[dict] = []
    seen: set[int] = set()
    with closing(open_index(database)) as connection:
        for fts_query in modes:
            rows = connection.execute(
                """SELECT rowid, root, path, page, bbox, body, bm25(passages) AS score,
                          snippet(passages, -1, '**', '**', ' … ', 32) AS snippet
                   FROM passages
                   WHERE passages MATCH ?
                   ORDER BY score ASC
                   LIMIT ?""",
                (fts_query, limit),
            ).fetchall()
            for row in rows:
                if row["rowid"] not in seen and len(results) < limit:
                    seen.add(row["rowid"])
                    hit = dict(row)
                    hit["id"] = hit.pop("rowid")  # passage id, used to fuse rankings
                    results.append(hit)
            if len(results) >= limit:
                break
    return results


def citation(result: dict) -> str:
    name = result["path"]
    if result["page"]:
        coordinate = f", bbox {result['bbox']}" if result["bbox"] else ""
        return f"{name}, page {result['page']}{coordinate}"
    return name
