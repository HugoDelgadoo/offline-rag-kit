# Architecture

This describes the code as of the current development version. Planned work is in the [roadmap](../ROADMAP.md).

```text
Local .pdf / .txt / .md
        |
        v   offline-rag ingest  (incremental: unchanged files are skipped)
PyMuPDF / UTF-8 text extraction
  - PDF text blocks (hyphenated line breaks rejoined)
  - PDF tables detected by PyMuPDF -> one passage per table
        |
        v
SQLite file (one local database)
  - passages   FTS5 table: root, path, page, bbox, body
  - files      path, size, mtime, content hash + extractor version
  - embeddings passage_rowid, model, dim, float32 vector   (only after `embed`)
        |
        +--> lexical:  BM25 (all terms first, then any term) ------+
        |                                                          |
        +--> vector:   cosine over stored vectors  <-- Ollama --+  +--> hybrid: Reciprocal Rank Fusion
                       (offline-rag embed, explicit step)       |  |
                                                                v  v
                                         CLI search / --json, citations (file, page, bbox)
                                                                |
                                                                +--> `ask`: local Ollama writes an answer from the hits
```

## Modules (`src/offline_rag/`)

| Module | Responsibility |
| --- | --- |
| `index.py` | Schema, extraction, incremental `ingest`, stale-data cleanup, BM25 `search`, `citation` |
| `embeddings.py` | Ollama embedder, `embed_index`, `vector_search`, `hybrid_search` (RRF) |
| `ollama.py` | Ollama host validation (loopback only by default) and answer generation |
| `cli.py` | Argument parsing, text and `--json` output |
| `eval.py` | Recall@k and MRR over `eval/questions.json` |

## Privacy boundary

The application opens only local files and creates a local SQLite database. Lexical search and `ingest` never use the network. The optional commands that talk to Ollama (`ask`, `embed`, `search --mode vector|hybrid`) accept only loopback hosts (`127.0.0.1`, `localhost`, `::1`) unless `--allow-remote` is passed, and they do not call external model APIs. Dependencies and the user's system configuration still determine actual security properties; see [SECURITY.md](../SECURITY.md).

## Index details

- **Paths are relative.** A passage stores the ingested folder (`root`) and its path relative to it, so citations do not leak local directory names and a moved folder does not leave duplicates (passages of folders that no longer exist are dropped on the next `ingest`).
- **Incremental ingest.** A file is skipped when its size and modification time match, or its SHA-256 matches. The stored hash is prefixed with an extractor version, so files indexed by an older extractor are re-extracted once after an upgrade.
- **Failures do not abort.** An unreadable file (corrupt or encrypted PDF, non-UTF-8 text) is reported and keeps its previous passages.
- **Deletes cascade.** Re-indexing or deleting a file removes its passages and its vectors in the same transaction.
- **Old indexes.** An index created before relative paths were introduced is rejected with an explicit message to rebuild it.

## How citations work

`pymupdf.Page.get_text("blocks")` returns text blocks and their (x0,y0,x1,y1) coordinates in PDF points. Each searchable block stores the ingested folder and its path relative to it, its 1-based page number and its bounding box; the CLI prints them alongside search hits. A detected table is one passage with the table's bounding box. Text documents get a filename citation. This does not yet produce highlighted PDF overlays or claim-exact coordinates.

## Retrieval

- **Lexical.** Query terms are quoted (FTS5 operators typed by the user are inert). Passages that contain every term rank first; remaining result slots are filled with passages matching any term. Hits include an FTS5 snippet with the matching terms highlighted.
- **Vector.** `embed` sends passage text to a local Ollama model (`/api/embed`) and stores L2-normalised float32 vectors. Search embeds the question with the same model and scans all vectors (pure Python, no extra dependencies). The index remembers its model; switching requires `--rebuild`.
- **Hybrid.** The lexical and vector rankings are fused with Reciprocal Rank Fusion (k = 60); the default search mode stays lexical.

## Evaluation

`python -m offline_rag.eval` runs a small bundled, synthetic dataset (four languages, 27 questions) and reports recall@k and MRR for any mode; see [EVALUATION.md](EVALUATION.md). Larger public test corpora, a manual audit of model-generated citations, and automated hallucination metrics remain future work: those metrics only make sense once a reliable reference dataset exists. The design notes for semantic retrieval are in [DESIGN-hybrid-retrieval.md](DESIGN-hybrid-retrieval.md).
