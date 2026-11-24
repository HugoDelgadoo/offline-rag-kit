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
- [ ] Better PDF paragraph/table extraction
- [x] Structured JSON output and benchmark queries
- [x] Error handling for encrypted or broken PDFs

## v0.3 — semantic and hybrid retrieval
- [ ] Local embedding model and Qdrant option
- [ ] Fusion of lexical + vector hits (RRF)
- [ ] Local reranking
- [ ] Question-answer faithfulness evaluation with versioned datasets

## v0.4 — more modalities
- [ ] OCR for scanned pages and citation overlays
- [ ] Audio transcription using offline inference
- [ ] Code-aware chunking and line-level references

## v1.0 — developer and enterprise usability
- [ ] Self-hosted HTTP API and web UI
- [ ] Multi-user permissions and tenancy boundaries
- [ ] Reproducible performance/security evaluations
- [ ] Containerized deployment and comprehensive docs

Community feedback should determine priority; avoid shipping unused complexity.
