# Design proposal: hybrid retrieval (issue #4)

Status: **proposal, nothing implemented.** Feedback welcome in the issue before any code is written.

## Goal

Find passages that mean the same thing as the question even when they share no words ("Who helps newcomers?" vs. "a buddy is assigned to new hires"), without breaking the project's promises: everything runs locally, the default install stays small, and citations (file, page, bounding box) keep working.

## Non-goals

- No hosted vector database or cloud embedding API.
- No change to the default behavior for people who do not opt in.
- No reranking model in this step (that is a later item in the roadmap).

## Decisions and alternatives

### 1. Where do embeddings come from?

| Option | Pros | Cons |
| --- | --- | --- |
| **Local Ollama `/api/embed`** (recommended first backend) | Already an optional dependency of the project; no new Python packages; loopback-only check already exists (`resolve_host`); user picks the model | Needs Ollama running and an embedding model pulled |
| sentence-transformers | Works without Ollama | Pulls in PyTorch (hundreds of MB); downloads models from the internet on first use |
| fastembed / ONNX runtime | Lighter than PyTorch | Still downloads a model from the internet on first use; another dependency to maintain |

Proposal: define a tiny interface (`embed(texts: list[str]) -> list[list[float]]`) and ship the Ollama backend first. Other backends can be added later behind the same interface.

Model choice matters for non-English content. A multilingual model (for example `bge-m3`) is probably a better default than an English-only one, but model names, sizes and quality should be **verified on the evaluation set** before choosing a default; this proposal does not claim numbers.

### 2. Where are vectors stored?

| Option | Pros | Cons |
| --- | --- | --- |
| **Plain SQLite table with float32 BLOBs + brute-force cosine** (recommended first) | No new service; same single file; easy to inspect; fine for tens of thousands of passages | Linear scan; needs numpy (optional extra) to be fast |
| `sqlite-vec` extension | Real vector index inside SQLite | Native extension: packaging and platform (Windows!) friction |
| Qdrant | Scales well | Separate server; contradicts the "one local file" simplicity |

Proposal: start with BLOBs + numpy (extra `offline-rag-kit[vectors]`). Revisit `sqlite-vec` if scans become too slow in the evaluation.

Rough index cost: a 1024-dimension float32 vector is 4 KiB per passage, so 100k passages is about 400 MiB. Quantization is a possible later optimization.

### 3. Schema

```text
embeddings(
  passage_rowid INTEGER PRIMARY KEY,   -- rowid of the row in the FTS5 table
  model TEXT NOT NULL,                 -- e.g. "bge-m3"
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL                 -- float32, little endian
)
```

- Re-indexing a file deletes its old passages **and** their embeddings in the same transaction.
- Changing the model invalidates the old vectors (detected through the `model` column); the user is told to re-embed rather than silently mixing models.
- Embeddings are produced by a separate step (`offline-rag embed`, or `ingest --embed`), only for passages that do not have one yet, so plain `ingest` stays fast and offline-only.

### 4. Query path

1. Lexical: the existing BM25 search (AND first, OR as fallback) returns the top N.
2. Vector: embed the question, cosine-score all vectors of the same model, return the top N.
3. **Reciprocal Rank Fusion**: `score(d) = Σ 1 / (k + rank_i(d))` with `k = 60`, over both ranked lists. RRF needs no score normalization, which is why it is preferred here over mixing BM25 and cosine scores.
4. Return the fused top `limit` with the same fields as today (`path`, `page`, `bbox`, `snippet`, ...), so the CLI, `--json` and `ask` keep working. Add an optional `scores` field to explain where a hit came from.

### 5. CLI

```text
offline-rag embed [--model bge-m3] [--ollama-host URL]
offline-rag search "..." --mode lexical|vector|hybrid   # default: lexical, or hybrid if embeddings exist
```

The default must stay predictable: `lexical` unless the user has embedded their documents, so nobody gets surprising network calls to Ollama from a plain `search`.

### 6. Long passages

Embedding models have a context limit. Passages longer than the limit are truncated or split into overlapping windows for embedding only; the stored passage and its citation do not change. The exact limit depends on the model and must be read from the model, not hard-coded.

### 7. Privacy

Same rule as `ask`: the Ollama host must be loopback unless `--allow-remote` is passed, because passage text would otherwise leave the machine. Documented in `SECURITY.md`.

## How we decide it works

The current evaluation set is **too easy to prove anything**: the "paraphrase" questions already share incidental words with their answers, and BM25 reaches recall@5 = 1.0. Before implementing, the dataset needs a harder subset:

- Questions with no content word in common with the answer passage.
- Cross-lingual pairs, if multilingual models are in scope.
- More documents, so that ranking mistakes are possible.

Acceptance criteria:

- Hybrid improves recall@1/MRR on the hard subset.
- Hybrid does not reduce the lexical subset (exact identifiers, numbers, names).
- Indexing time and index size are reported in `docs/EVALUATION.md` next to the quality numbers.

## Proposed split into small PRs

1. Harder evaluation subset (can be done independently, and is useful on its own).
2. Embedding interface + Ollama backend + `embeddings` table + `embed` command (no search changes yet).
3. Vector search and RRF behind `--mode`, with tests that use a fake embedder (no Ollama needed in CI).
4. Documentation, CHANGELOG, evaluation numbers.

## Open questions

- Is Ollama as the first and only backend acceptable, or is a dependency-free option (pure ONNX) a must?
- Which default model, given content in several languages?
- Is a maximum index size a concern for typical users (for example laptops with a few thousand PDFs)?
- Should `ingest` ever embed automatically, or must it always be an explicit step?
