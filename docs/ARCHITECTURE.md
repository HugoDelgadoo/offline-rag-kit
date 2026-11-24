# Architecture (v0.1)

```text
Local .pdf / .txt / .md
        |
        v
PyMuPDF / UTF-8 text extraction
        |
        v
Text blocks / paragraphs + source metadata
        |
        v
SQLite FTS5 index (local file)
        |
        v
BM25 lexical retrieval
        |
        +----> CLI search, page and bbox citations
        |
        +----> local Ollama (optional) ---> Answer and retrieved evidence
```

## Privacy boundary

The application opens only local files and creates a local SQLite database. Optional generation sends selected evidence to an Ollama server listening on `127.0.0.1:11434`; it does not call external model APIs. Like any local software, dependencies and the user's system configuration determine actual security properties.

## How citations work

`pymupdf.Page.get_text("blocks")` returns text blocks and their (x0,y0,x1,y1) coordinates in PDF points. Each searchable block stores the ingested folder and its path relative to it, 1-based page number, and bounding box; the CLI prints them alongside search hits. Text documents get a filename citation. This does not yet produce highlighted PDF overlays or claim-exact coordinates.

## Evaluation direction

Use a versioned public test corpus with expected passages, evaluate recall@k and MRR for retrieval, and manually audit model-generated citations. Add automated hallucination metrics only after a reliable reference dataset exists.
