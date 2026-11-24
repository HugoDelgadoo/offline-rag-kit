# Security policy

This is an alpha single-user prototype. It has not undergone a formal security audit.
Do **not** expose the Ollama service or local document index to untrusted networks.
For a suspected vulnerability, please avoid posting exploit details or sensitive files in a public issue. Instead, contact maintainers privately using GitHub's private vulnerability reporting feature if enabled, or open a public issue with only non-sensitive context requesting a private channel.

Retrieval content is untrusted and may contain prompt injection. The local model can still make incorrect claims; citations need human verification. PDF and text parsers should be used with care on untrusted files.

The Ollama host defaults to loopback. `OLLAMA_HOST` / `--ollama-host` pointing to a non-loopback address is refused unless `--allow-remote` is passed, since that sends retrieved passages to another machine.

`offline-rag serve` listens on `127.0.0.1` only (there is no option to change the address), accepts only GET requests, never writes to the index or the documents, and refuses requests whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding). `/api/info` and `/api/files` return the paths of the indexed folders and files, only to the loopback address and subject to the same Host check. The PDF preview is requested by passage id, not by path: the server looks the file up in the index, refuses anything outside the ingested folder, and never saves the PDF. Any other program running as you on the same computer can still query it while it runs, so stop it when you are done.

`offline-rag embed` and `search --mode vector|hybrid` send passage text and questions to the configured Ollama host for embedding, under the same loopback-only rule (`--allow-remote` to override). Embeddings are stored unencrypted in the index file and can leak information about the documents, so protect the index like the documents themselves.
