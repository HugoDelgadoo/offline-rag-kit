# Offline RAG Kit

**Privacy-first local document search with PDF citations and optional local AI answers.**

> **Status: v0.1 alpha — a working retrieval-first prototype, not yet a complete multimodal RAG system.**

Offline RAG Kit helps developers find evidence in local PDFs, Markdown and plain-text documents without sending private files to the cloud. It uses SQLite FTS5 for lexical search, records PDF page numbers and block coordinates, and can optionally generate evidence-grounded answers through a locally running Ollama model.

## Why this project?

- **Local-first:** files and index stay on your machine.
- **Auditable sources:** PDF hits include page number and bounding box (x0,y0,x1,y1).
- **Easy to run:** Python, PyMuPDF and SQLite; no remote account required.
- **No cloud inference:** optional generation calls `127.0.0.1:11434` only.
- **Useful foundation:** roadmap includes hybrid vector/BM25 retrieval, OCR, audio, reranking and automated evaluations.

## Quickstart (Windows PowerShell)

Requirements: Python 3.10 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
offline-rag ingest .\demo
offline-rag search "SQLite"
```

Search real files:

```powershell
offline-rag ingest "C:\Users\YourUser\Documents\knowledge"
offline-rag search "retention policy"
```

To ask questions using a local model, first [install Ollama](https://ollama.com/) and pull a model:

```powershell
ollama pull llama3.2
offline-rag ask "How are PDFs cited?" --model llama3.2
```

The `ask` command uses a **local** Ollama server only. It cannot guarantee the model will never hallucinate; verify citations before relying on generated responses.

## Command reference

```text
offline-rag [--db PATH] [--json] ingest FOLDER
offline-rag [--db PATH] [--json] search "TERMS" [--limit 5]
offline-rag [--db PATH] [--json] ask "QUESTION" [--limit 5] [--model llama3.2]
```

`--json` (placed before the subcommand) prints a single JSON document on stdout, with the full passage text, page, bounding box and score for each hit. Errors and exit codes are unchanged and still go to stderr.

## Current capabilities and limitations

| Capability | Status |
| --- | --- |
| Recursively ingest PDF / Markdown / TXT | Supported |
| Lexical ranking with SQLite FTS5 (BM25) | Supported |
| PDF source pages and block bounding boxes | Supported |
| Local Ollama text generation | Optional, supported |
| Semantic / vector retrieval | Planned |
| OCR, image understanding, audio transcription | Planned |
| Web dashboard / user authentication | Planned |
| Reliable claim-level grounding evaluation | Planned |

The first version **does not** OCR scanned PDFs or interpret PDF tables reliably. Each PDF text block is a retrieval unit, so coordinates describe blocks rather than arbitrary answer spans. Changed files are refreshed on re-ingest; deleted files currently require rebuilding the index. This is a single-user developer prototype, not a hardened multi-user service.

## Development

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

See [ROADMAP](ROADMAP.md), [architecture](docs/ARCHITECTURE.md) and [contribution guide](CONTRIBUTING.md). Contributions, reproducible bug reports and small real-world test datasets (without confidential content) are welcome.

## Maintainer

Created and maintained by [@HugoDelgadoo](https://github.com/HugoDelgadoo). See the [changelog](CHANGELOG.md) for release notes.

## License

MIT — see [LICENSE](LICENSE).
