# Security policy

This is an alpha single-user prototype. It has not undergone a formal security audit.
Do **not** expose the Ollama service or local document index to untrusted networks.
For a suspected vulnerability, please avoid posting exploit details or sensitive files in a public issue. Instead, contact maintainers privately using GitHub's private vulnerability reporting feature if enabled, or open a public issue with only non-sensitive context requesting a private channel.

Retrieval content is untrusted and may contain prompt injection. The local model can still make incorrect claims; citations need human verification. PDF and text parsers should be used with care on untrusted files.

The Ollama host defaults to loopback. `OLLAMA_HOST` / `--ollama-host` pointing to a non-loopback address is refused unless `--allow-remote` is passed, since that sends retrieved passages to another machine.

`offline-rag embed` and `search --mode vector|hybrid` send passage text and questions to the configured Ollama host for embedding, under the same loopback-only rule (`--allow-remote` to override). Embeddings are stored unencrypted in the index file and can leak information about the documents, so protect the index like the documents themselves.
