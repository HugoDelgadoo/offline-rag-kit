# Demo knowledge base

Offline RAG Kit indexes local Markdown, plain-text and PDF documents. The index is stored in SQLite FTS5, without uploading files.

For PDF documents, each retrieved text block includes its original page number and bounding-box coordinates.

Answer generation is optional and calls Ollama on the local loopback address 127.0.0.1. Retrieval works without Ollama.
