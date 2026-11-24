"""Optional semantic retrieval with embeddings from a local Ollama server.

Nothing here runs unless the user asks for it: ``offline-rag embed`` creates the vectors
(an explicit step), and ``search --mode vector|hybrid`` uses them. Only the Python standard
library is needed; vectors live in the same SQLite file as the passages.
"""

from __future__ import annotations

import heapq
import json
import math
import operator
import struct
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .index import open_index, search
from .ollama import resolve_host

DEFAULT_MODEL = "bge-m3"  # multilingual; pull it first with `ollama pull bge-m3`
Embedder = Callable[[list[str]], list[list[float]]]


def ollama_embedder(
    model: str, host: str | None = None, allow_remote: bool = False, timeout: int = 180
) -> Embedder:
    """Return a function that embeds texts through Ollama's ``/api/embed`` endpoint."""
    base_url = resolve_host(host, allow_remote)  # refuses non-loopback hosts by default

    def embed(texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": model, "input": texts, "truncate": True}).encode("utf-8")
        request = Request(
            f"{base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                data = json.load(response)
        except HTTPError as exc:
            detail = ""
            try:
                detail = json.load(exc).get("error", "")
            except Exception:
                pass
            hint = f" Run: ollama pull {model}" if exc.code == 404 else ""
            raise RuntimeError(f"Ollama returned HTTP {exc.code} for model {model!r}: {detail}.{hint}") from exc
        except URLError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {base_url}. Run 'ollama serve' and 'ollama pull {model}'."
            ) from exc
        vectors = data.get("embeddings")
        if (
            not isinstance(vectors, list)
            or len(vectors) != len(texts)
            or not all(isinstance(v, list) and v for v in vectors)
        ):
            raise RuntimeError("Unexpected response from Ollama's /api/embed endpoint.")
        return vectors

    return embed


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise ValueError("The embedding model returned a zero vector.")
    return [x / norm for x in vector]


def _encode(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _decode(blob: bytes) -> tuple[float, ...]:
    return struct.unpack(f"<{len(blob) // 4}f", blob)


def indexed_model(database: str | Path) -> str | None:
    """Model that produced the vectors in this index, or None if it has none."""
    with closing(open_index(database)) as connection:
        models = [row[0] for row in connection.execute("SELECT DISTINCT model FROM embeddings")]
    if len(models) > 1:
        raise ValueError(f"Index mixes embeddings from several models: {', '.join(sorted(models))}.")
    return models[0] if models else None


def embed_index(
    database: str | Path,
    embedder: Embedder,
    model: str,
    batch_size: int = 16,
    rebuild: bool = False,
) -> int:
    """Embed every passage that has no vector yet; return how many were embedded."""
    with closing(open_index(database)) as connection:
        if rebuild:
            with connection:
                connection.execute("DELETE FROM embeddings")
        existing = [row[0] for row in connection.execute("SELECT DISTINCT model FROM embeddings")]
        if existing and existing != [model]:
            raise ValueError(
                f"This index already has embeddings from {existing[0]!r}. "
                f"Use --rebuild to replace them with {model!r}."
            )
        todo = connection.execute(
            """SELECT p.rowid AS id, p.body FROM passages p
               LEFT JOIN embeddings e ON e.passage_rowid = p.rowid
               WHERE e.passage_rowid IS NULL ORDER BY p.rowid"""
        ).fetchall()
        dims = {row[0] for row in connection.execute("SELECT DISTINCT dim FROM embeddings")}
        for start in range(0, len(todo), batch_size):
            batch = todo[start:start + batch_size]
            vectors = [_normalize(v) for v in embedder([row["body"] for row in batch])]
            dims |= {len(v) for v in vectors}
            if len(dims) > 1:
                raise ValueError("The embedding model returned vectors of different sizes.")
            with connection:
                connection.executemany(
                    "INSERT OR REPLACE INTO embeddings (passage_rowid, model, dim, vector) VALUES (?, ?, ?, ?)",
                    ((row["id"], model, len(v), _encode(v)) for row, v in zip(batch, vectors, strict=True)),
                )
    return len(todo)


def vector_search(query: str, database: str | Path, embedder: Embedder, limit: int = 5) -> list[dict]:
    """Rank passages by cosine similarity to the query (brute force over all vectors)."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    with closing(open_index(database)) as connection:
        stored = connection.execute("SELECT passage_rowid, dim, vector FROM embeddings").fetchall()
        if not stored:
            raise ValueError("This index has no embeddings. Run 'offline-rag embed' first.")
        query_vector = _normalize(embedder([query])[0])
        if len(query_vector) != stored[0]["dim"]:
            raise ValueError("The query embedding does not match the indexed vectors: was the model changed?")
        dot = operator.mul
        scored = (
            (sum(map(dot, query_vector, _decode(row["vector"]))), row["passage_rowid"]) for row in stored
        )
        top = heapq.nlargest(limit, scored)
        hits = []
        for score, rowid in top:
            row = connection.execute(
                "SELECT root, path, page, bbox, body FROM passages WHERE rowid = ?", (rowid,)
            ).fetchone()
            if row:
                body = row["body"]
                hits.append({
                    "id": rowid, "root": row["root"], "path": row["path"], "page": row["page"],
                    "bbox": row["bbox"], "body": body, "score": score,
                    "snippet": body if len(body) <= 240 else body[:240].rstrip() + " …",
                })
    return hits


def hybrid_search(
    query: str, database: str | Path, embedder: Embedder, limit: int = 5, k: int = 60
) -> list[dict]:
    """Fuse BM25 and vector rankings with Reciprocal Rank Fusion."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    pool = min(100, max(limit * 4, 20))
    rankings = [search(query, database, pool), vector_search(query, database, embedder, pool)]
    fused: dict[int, float] = {}
    best: dict[int, dict] = {}
    for hits in rankings:
        for rank, hit in enumerate(hits, start=1):
            fused[hit["id"]] = fused.get(hit["id"], 0.0) + 1.0 / (k + rank)
            best.setdefault(hit["id"], hit)  # the lexical hit comes first and has a highlighted snippet
    ordered = sorted(fused, key=lambda i: (-fused[i], i))[:limit]
    return [{**best[i], "score": fused[i]} for i in ordered]
