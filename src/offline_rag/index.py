"""SQLite FTS5 search index with PDF page and bounding-box citations."""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Iterator

import fitz

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}


def open_index(database: str | Path) -> sqlite3.Connection:
    target = Path(database).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
            path UNINDEXED,
            page UNINDEXED,
            bbox UNINDEXED,
            body,
            tokenize = 'unicode61 remove_diacritics 2'
        )"""
    )
    return connection


def extract_passages(path: Path) -> Iterator[tuple[int, str, str]]:
    """Yield (page number, bounding box, paragraph text). Page 0 means text file."""
    if path.suffix.lower() == ".pdf":
        with fitz.open(path) as document:
            for page_number, page in enumerate(document, start=1):
                for block in page.get_text("blocks"):
                    if len(block) > 6 and block[6] != 0:
                        continue  # Skip image blocks.
                    body = " ".join(str(block[4]).split())
                    if not body:
                        continue
                    bbox = ",".join(f"{float(n):.1f}" for n in block[:4])
                    yield page_number, bbox, body
    else:
        text = path.read_text(encoding="utf-8-sig")
        for paragraph in re.split(r"\n\s*\n", text):
            body = " ".join(paragraph.split())
            if body:
                yield 0, "", body


def ingest(
    folder: str | Path,
    database: str | Path,
    on_error: Callable[[Path, Exception], None] | None = None,
) -> tuple[int, int]:
    """Index all documents recursively; re-ingesting a file replaces its passages.

    Files that cannot be read (corrupt or encrypted PDFs, non-UTF-8 text) are
    skipped and reported through ``on_error``; their previous passages, if any,
    are kept. Passages of files that no longer exist under ``folder`` are removed.
    Returns (files indexed, passages indexed).
    """
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Folder not found: {root}")
    documents = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    file_count = 0
    passage_count = 0
    with closing(open_index(database)) as connection:
        for path in documents:
            try:
                entries = list(extract_passages(path))
            except Exception as exc:  # parsers raise many different error types
                if on_error:
                    on_error(path, exc)
                continue
            with connection:
                connection.execute("DELETE FROM passages WHERE path = ?", (str(path),))
                connection.executemany(
                    "INSERT INTO passages (path, page, bbox, body) VALUES (?, ?, ?, ?)",
                    ((str(path), page, bbox, body) for page, bbox, body in entries),
                )
            file_count += 1
            passage_count += len(entries)
        _remove_stale(connection, root, {str(path) for path in documents})
    return file_count, passage_count


def _remove_stale(connection: sqlite3.Connection, root: Path, present: set[str]) -> None:
    """Delete passages of files under ``root`` that are no longer on disk."""
    prefix = str(root) + os.sep
    indexed = [row[0] for row in connection.execute("SELECT DISTINCT path FROM passages")]
    stale = [path for path in indexed if path.startswith(prefix) and path not in present]
    with connection:
        connection.executemany("DELETE FROM passages WHERE path = ?", ((p,) for p in stale))


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
                """SELECT rowid, path, page, bbox, body, bm25(passages) AS score
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
                    del hit["rowid"]
                    results.append(hit)
            if len(results) >= limit:
                break
    return results


def citation(result: dict) -> str:
    name = Path(result["path"]).name
    if result["page"]:
        coordinate = f", bbox {result['bbox']}" if result["bbox"] else ""
        return f"{name}, page {result['page']}{coordinate}"
    return name
