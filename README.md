# Offline RAG Kit

[![CI](https://github.com/HugoDelgadoo/offline-rag-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/HugoDelgadoo/offline-rag-kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/offline-rag-kit)](https://pypi.org/project/offline-rag-kit/)
[![Python](https://img.shields.io/pypi/pyversions/offline-rag-kit)](https://pypi.org/project/offline-rag-kit/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/LICENSE)

**English** | [Español](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/README.es.md)

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
python -m pip install offline-rag-kit
offline-rag ingest .\demo
offline-rag search "SQLite"
```

Search real files:

```powershell
offline-rag ingest "C:\Users\YourUser\Documents\knowledge"
offline-rag search "retention policy"
```

### Use it from any terminal, and where the index lives

- **Install once, use anywhere:** `pipx install offline-rag-kit` makes the `offline-rag` command available in every terminal. With plain `pip` inside a virtual environment it only works while that environment is active. If your terminal says `offline-rag` is not recognized, Python's scripts folder is not on your `PATH`; `pipx ensurepath` fixes that.
- **The index lives in one fixed folder per user**, so it works from any directory: `%LOCALAPPDATA%\offline-rag\index.sqlite3` on Windows, `~/Library/Application Support/offline-rag/` on macOS, `~/.local/share/offline-rag/` on Linux. Run `offline-rag --json ingest FOLDER` to see the exact path (`database`). To use another file, pass `--db PATH` or set `OFFLINE_RAG_DB`:

```powershell
offline-rag --db C:\Users\You\my-index.sqlite3 ingest C:\Users\You\Documents
```

- If you used an older version, an index in `.offline-rag/` inside the current folder is still used (with a hint) until a fixed-location index exists; move the file to the new location to use it from anywhere.

To ask questions using a local model, first [install Ollama](https://ollama.com/) and pull a model:

```powershell
ollama pull llama3.2
offline-rag ask "How are PDFs cited?" --model llama3.2
```

The `ask` command uses a **local** Ollama server only. It cannot guarantee the model will never hallucinate; verify citations before relying on generated responses.

## Command reference

```text
offline-rag [--db PATH] [--json] ingest FOLDER
offline-rag [--db PATH] [--json] search "TERMS" [--limit 5] [--mode lexical|vector|hybrid] [--files]
offline-rag [--db PATH] [--json] embed [--model bge-m3] [--rebuild] [--ollama-host URL] [--allow-remote]
offline-rag [--db PATH] [--json] ask "QUESTION" [--limit 5] [--model llama3.2]
                                     [--ollama-host URL] [--allow-remote]
```

### Which files contain a word?

By default `search` prints the best matching **passages** (the same file can appear several times). To get a list of **files** instead, add `--files`: each file appears once, with its full path, how many passages match and, for PDFs, the pages.

```powershell
offline-rag search "policy" --files
```

```text
3 files contain 'policy':
  C:\Users\You\Documents\notes\meeting.md  (2 matching passages)
  C:\Users\You\Documents\handbook.md  (1 matching passage)
  C:\Users\You\Documents\contract.pdf  (2 matching passages; pages 1, 3)
```

Files containing **every** word are listed; if there are none, files containing at least one word are listed and the output says so. `--limit` (default 20, up to 100) caps the list, while the first line always shows the total. `--files` works only in the default lexical mode.

Re-running `ingest` is incremental: unchanged files (by content hash) are not re-parsed.

`ask` talks to `127.0.0.1:11434` by default. Set `OLLAMA_HOST` or `--ollama-host` to use another port. Non-loopback hosts are refused unless you pass `--allow-remote`, because retrieved passages would then leave your machine.

### Optional semantic search (local Ollama)

Plain `search` is lexical and works fully offline. To also match by meaning (for example "work from home" ~ "teletrabajo"), create embeddings **explicitly** with a local Ollama model, then choose a mode:

```powershell
ollama pull bge-m3                       # a multilingual embedding model
offline-rag embed --model bge-m3         # explicit step; only embeds new passages
offline-rag search "work from home" --mode hybrid   # BM25 + vectors fused (RRF)
offline-rag search "work from home" --mode vector   # vectors only
```

- `ingest` never calls Ollama, and the default mode stays `lexical`. Semantic modes need Ollama running when you search, because the question must be embedded too.
- The index remembers which model made its vectors. Switching models needs `offline-rag embed --model NEW --rebuild`.
- Same privacy rule as `ask`: only loopback hosts are accepted unless you pass `--allow-remote`.
- Vectors are compared with a plain scan, which is fine for thousands of passages but slows down on very large collections. Embedding speed depends on your hardware and model.
- **Not yet measured with a real model.** Use `python -m offline_rag.eval --mode hybrid --model bge-m3` to see what it does on the bundled dataset.

`--json` (placed before the subcommand) prints a single JSON document on stdout, with the full passage text, page, bounding box and score for each hit. Errors and exit codes are unchanged and still go to stderr.

## Current capabilities and limitations

| Capability | Status |
| --- | --- |
| Recursively ingest PDF / Markdown / TXT | Supported |
| Lexical ranking with SQLite FTS5 (BM25) | Supported |
| PDF source pages and block bounding boxes | Supported |
| Local Ollama text generation | Optional, supported |
| Semantic / vector retrieval | Optional, via local Ollama embeddings (not yet benchmarked) |
| OCR, image understanding, audio transcription | Planned |
| Web dashboard / user authentication | Planned |
| Reliable claim-level grounding evaluation | Planned |

The first version **does not** OCR scanned PDFs. Tables that PyMuPDF detects (ruled, and often well-aligned borderless ones) are indexed as one passage per table; detection is heuristic and can miss or misread complex layouts. Words split by a hyphen at a line end are rejoined. Each PDF text block is a retrieval unit, so coordinates describe blocks rather than arbitrary answer spans. Changed files are refreshed on re-ingest and deleted files are removed from the index. This is a single-user developer prototype, not a hardened multi-user service.

## Evaluation

```powershell
python -m offline_rag.eval
```

Measures recall@k and MRR on a small bundled dataset (`eval/`). See [docs/EVALUATION.md](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/docs/EVALUATION.md) for the current baseline.

## Development

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

See [ROADMAP](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/ROADMAP.md), [architecture](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/docs/ARCHITECTURE.md) and [contribution guide](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/CONTRIBUTING.md). Contributions, reproducible bug reports and small real-world test datasets (without confidential content) are welcome.

## Maintainer

Created and maintained by [@HugoDelgadoo](https://github.com/HugoDelgadoo). See the [changelog](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/CHANGELOG.md) for release notes.

## License

MIT — see [LICENSE](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/LICENSE).
