# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [Semantic Versioning](https://semver.org/) (0.x versions may change the CLI).

## [Unreleased]

### Changed
- Web interface polish, following the Web Interface Guidelines: the PDF preview now shows a band of the page around the passage (with a "Show Full Page" toggle; `/preview?id=N&full=1` renders the whole page); the Files view shows the file name and its folder separately; result counts ("5 passages", "2 files"); clearer empty-state and error messages with a next step; visible hover and focus states, a real label, toggle buttons with `aria-pressed` and `aria-expanded`, non-breaking spaces, `theme-color`, touch-friendly buttons, and the search box is focused on load only on devices with a mouse.

### Fixed
- The Windows installer starts the program as `python -m offline_rag.cli` from its private environment instead of the `offline-rag.exe` that pip generates, because that unsigned launcher is blocked on PCs with Windows App Control / Smart App Control ("a policy blocked this file"). The `offline-rag` command, the Start Menu entries and the folder picker all use it. (The installer is not part of the PyPI package, so this needs no new release.)

## [0.1.5] - 2026-11-24

### Added
- `offline-rag serve [--port 8765] [--open]`: a local, read-only web interface (search passages with highlighted terms, or list files). It binds to `127.0.0.1` only, refuses requests with a foreign `Host` header, accepts only GET, sets a strict Content-Security-Policy, renders document text without HTML injection, and uses only the standard library. For PDF results, "Show page" renders the page as an image with the passage highlighted (`/preview?id=N`). The preview is found through the index (the browser never sends a path), only for files inside the indexed folder, and the PDF is opened read-only.
- Windows installer: `scripts/install-windows.ps1` installs the program in a private virtual environment for the current user (no administrator rights), adds the `offline-rag` command to the user PATH and creates Start Menu entries ("Offline RAG" opens the web interface, "Offline RAG - index a folder" asks for a folder and indexes it). `scripts/uninstall-windows.ps1` removes it and keeps your documents and index. CI installs, runs and uninstalls it on Windows.

### Changed
- The default index is now a fixed per-user file (`%LOCALAPPDATA%\offline-rag\index.sqlite3` on Windows, `~/Library/Application Support/offline-rag/` on macOS, `$XDG_DATA_HOME` or `~/.local/share/offline-rag/` on Linux) instead of `.offline-rag/` in the current folder, so `search` works from any directory. `--db` and the new `OFFLINE_RAG_DB` variable override it. An index left in `.offline-rag/` of the current folder is still used, with a hint, until a fixed-location index exists.

## [0.1.4] - 2026-11-24

### Added
- `search --files` lists each file that contains the words once, with its full path, the number of matching passages, the PDF pages and the total number of files (also in `--json`). Files containing every word come first; if none do, files containing any word are listed.

### Changed
- README (English and Spanish): how to install once with `pipx`, and where the default index is stored (the folder where the command runs) and how to use `--db` for a fixed index.
- The PyPI workflow is a dry run when started manually (tick "publish" to upload), skips files already on PyPI, and CI actions are updated (`checkout` 7, `setup-python` 7, `upload-artifact` 7, `download-artifact` 8).

## [0.1.3] - 2026-11-24

### Added
- Optional (experimental, not yet measured with a real model) semantic search with local Ollama embeddings: `offline-rag embed` (explicit step), `search`/`ask --mode vector|hybrid` (BM25 + vectors fused with Reciprocal Rank Fusion). Vectors are stored in the same SQLite file; only the standard library is used. `ingest` never calls Ollama and the default mode stays `lexical`.
- `python -m offline_rag.eval --mode hybrid` to measure semantic retrieval on the bundled dataset.
- Spanish README (`README.es.md`) with a language switch.
- Evaluation set extended to 27 questions in four languages (hard paraphrases, multilingual and cross-lingual).
- Design notes in `docs/DESIGN-hybrid-retrieval.md`.

### Fixed
- A corrupt PDF stayed open after `ingest` reported it, so Windows refused to delete or move it. `IngestResult.skipped` now holds error messages instead of exception objects.

### Changed
- CI runs the tests on Ubuntu, Windows and macOS, plus a lint (ruff) and coverage job (minimum 80%); Dependabot proposes updates to GitHub Actions and pip dependencies weekly.
- `docs/ARCHITECTURE.md` rewritten to match the current code.
- Search hits carry an internal `id`; re-indexing or deleting a file also removes its vectors.

## [0.1.2] - 2026-11-24

### Added
- PDF words split by a hyphen at a line end ("docu-\nment") are rejoined so they can be found; a compound split exactly at a line end loses its hyphen.
- PDF tables detected by PyMuPDF (ruled, and often well-aligned borderless ones) are indexed as a single passage ("Item | Years; Invoices | 10; ...") with the table's bounding box, so a row stays connected to its header; text inside a table is no longer indexed twice.

### Changed
- Files indexed by an older extractor are re-extracted once on the next `ingest`, even if their content did not change.

## [0.1.1] - 2026-11-24

### Changed
- README: CI, PyPI, Python and license badges; links work on the PyPI page; install with `pip install offline-rag-kit`.

## [0.1.0] - 2026-11-24

First public alpha: a retrieval-first prototype for private, local document search.

### Added
- Recursive ingestion of PDF, Markdown and plain-text files into a local SQLite FTS5 index.
- BM25 retrieval. Passages containing all query terms rank first; remaining slots are
  filled with partial (any-term) matches. Query terms are quoted, so FTS5 operators in
  user input are inert.
- PDF citations with 1-based page number and block bounding box (x0,y0,x1,y1).
- `offline-rag ingest | search | ask` command line interface.
- Optional answers from a local Ollama server (`127.0.0.1:11434`) using only retrieved passages.
- `python -m offline_rag.eval` with a small bundled dataset (recall@k and MRR); baseline in `docs/EVALUATION.md`.
- `--json` global flag for machine-readable output of all commands.
- Unit tests, GitHub Actions CI (Python 3.10, 3.12, 3.13), and architecture, roadmap,
  security and contribution documents.

### Changed
- `ingest` is incremental (size/mtime shortcut plus SHA-256); the CLI reports how many files were unchanged, and `ingest()` returns an `IngestResult`.
- `ask` honours `OLLAMA_HOST` / `--ollama-host`; non-loopback hosts need `--allow-remote`.
- Citations and `--json` paths are relative to the ingested folder; the index stores the root
  separately. Indexes from earlier builds must be rebuilt (a clear error says so).
- `search` prints a snippet around the matching terms (`**term**`) and `--json` adds a `snippet` field.
- Use `import pymupdf` (no more `fitz` deprecation warning); requires PyMuPDF >= 1.24.3.
- Repository reorganized into `src/offline_rag/`, `tests/`, `docs/`, `demo/` and
  `.github/workflows/` so the package installs and CI runs.

### Fixed
- Moving or renaming a document folder no longer leaves duplicate passages after re-ingesting.
- A corrupt, encrypted or non-UTF-8 file no longer aborts ingestion; it is skipped and
  reported (warning on stderr, or in the `skipped` list with `--json`).
- Re-ingesting a folder removes passages of files deleted from it, leaving other folders
  in the same index untouched.
- SQLite connections are closed explicitly (no resource warnings or file locks on Windows).

### Known limitations
- No OCR for scanned PDFs and no reliable table extraction.
- Lexical search only; semantic/vector retrieval is planned (see [ROADMAP](ROADMAP.md)).
- Single-user prototype, not a hardened multi-user service.

[0.1.5]: https://github.com/HugoDelgadoo/offline-rag-kit/releases/tag/v0.1.5
[0.1.4]: https://github.com/HugoDelgadoo/offline-rag-kit/releases/tag/v0.1.4
[0.1.3]: https://github.com/HugoDelgadoo/offline-rag-kit/releases/tag/v0.1.3
[0.1.2]: https://github.com/HugoDelgadoo/offline-rag-kit/releases/tag/v0.1.2
[0.1.1]: https://github.com/HugoDelgadoo/offline-rag-kit/releases/tag/v0.1.1
[0.1.0]: https://github.com/HugoDelgadoo/offline-rag-kit/releases/tag/v0.1.0
