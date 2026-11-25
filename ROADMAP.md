# Roadmap

This roadmap is a plan, not a claim that future capabilities already exist.

## v0.1 — retrieval-first baseline (implemented)
- [x] Recursive local PDF, Markdown and TXT ingestion
- [x] SQLite FTS5/BM25 retrieval
- [x] PDF page + block bounding-box references
- [x] Optional local Ollama answers
- [x] Unit tests + GitHub Actions CI

## v0.2 — search correctness and useful maintenance
- [x] Delete stale entries when documents are removed
- [x] Filesystem content hashes and incremental indexing
- [ ] Better PDF paragraph/table extraction (basics done: tables as one passage, hyphenated line breaks rejoined; still needs real-world PDF samples, #3)
- [x] Structured JSON output and benchmark queries
- [x] Error handling for encrypted or broken PDFs
- [x] `search --files`: list the files that contain the words

## v0.3 — semantic and hybrid retrieval
- [x] Local embedding model (Ollama) with an explicit `embed` step; a Qdrant option is not planned for now (experimental: not yet measured with a real model, #4)
- [x] Fusion of lexical + vector hits (RRF)
- [ ] Local reranking
- [ ] Question-answer faithfulness evaluation with versioned datasets

## v0.4 — more modalities
- [x] Citation overlays: PDF page preview with the passage highlighted (text PDFs)
- [ ] OCR for scanned pages (#6)
- [ ] Audio transcription using offline inference
- [ ] Code-aware chunking and line-level references

## Usability (shipped in 0.1.5)
- [x] Fixed per-user default index, so `search` works from any folder
- [x] Local read-only web interface (`offline-rag serve`, loopback only, Spanish/English)
- [x] Windows install and uninstall scripts, tested in CI
- [ ] Standalone `.exe` built in CI

## v1.0 — developer and enterprise usability
- [x] Local web UI (see above)
- [ ] Self-hosted HTTP API (the current web UI is local, read-only and loopback only)
- [ ] Multi-user permissions and tenancy boundaries
- [ ] Reproducible performance/security evaluations
- [ ] Containerized deployment and comprehensive docs

Community feedback should determine priority; avoid shipping unused complexity.
