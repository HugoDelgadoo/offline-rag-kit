"""SQLite FTS5 search index with PDF page and bounding-box citations."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterator

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


def ingest(folder: str | Path, database: str | Path) -> tuple[int, int]:
    """Index all documents recursively; re-ingesting a file replaces its passages."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Folder not found: {root}")
    documents = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    passage_count = 0
    with open_index(database) as connection:
        for path in documents:
            entries = list(extract_passages(path))
            with connection:
                connection.execute("DELETE FROM passages WHERE path = ?", (str(path),))
                connection.executemany(
                    "INSERT INTO passages (path, page, bbox, body) VALUES (?, ?, ?, ?)",
                    ((str(path), page, bbox, body) for page, bbox, body in entries),
                )
            passage_count += len(entries)
    return len(documents), passage_count


def search(query: str, database: str | Path, limit: int = 5) -> list[dict]:
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    if not tokens:
        return []
    # Quoting every user token avoids injecting FTS5 operators or syntax.
    fts_query = " OR ".join(f'"{token}"' for token in tokens)
    with open_index(database) as connection:
        rows = connection.execute(
            """SELECT path, page, bbox, body, bm25(passages) AS score
               FROM passages
               WHERE passages MATCH ?
               ORDER BY score ASC
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def citation(result: dict) -> str:
    name = Path(result["path"]).name
    if result["page"]:
        coordinate = f", bbox {result['bbox']}" if result["bbox"] else ""
        return f"{name}, page {result['page']}{coordinate}"
    return name
