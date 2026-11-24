# Design proposal: hybrid retrieval (issue #4)

Status: **implemented in the Unreleased version** (see the outcome section at the end). Maintainer decisions are recorded at the end; they supersede the recommendations above where they differ.

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

## Maintainer decisions (2026-11-24) and revised plan

1. **A dependency-free option is required.** No new Python packages and no model download for the default experience.
2. **Documents can be in any language.**
3. **Embedding is always an explicit step** (`offline-rag embed`); `ingest` never embeds on its own.

### What "dependency-free" can and cannot deliver

A model that understands meaning ("buddy" ~ "mentor", "work from home" ~ "teletrabajo") needs trained weights, and weights need a runtime and a download. So there are two different goals:

- **Dependency-free, language-agnostic fuzzy matching** (character n-grams): finds word variants, typos, shared roots across languages ("vacation" ~ "vacaciones", "Flug" ~ "Flüge"). It does **not** understand synonyms or paraphrases.
- **Real semantic search**: requires a model. Keep it as an optional backend (Ollama first), behind the same interface, for people who want it.

### Prototype evidence (not production code)

A throwaway stdlib-only prototype (character 3-5-grams, TF-IDF, cosine, fused with BM25 by RRF) was run on the extended evaluation set (27 questions; see `docs/EVALUATION.md`):

| Method | R@1 overall | MRR overall | R@1 hard-paraphrase | R@1 cross-lingual |
| --- | --- | --- | --- | --- |
| BM25 (current) | 0.70 | 0.76 | 0.29 | 0.00 |
| char n-grams alone | 0.63 | 0.70 | 0.29 | 0.00 |
| BM25 + n-grams (RRF) | 0.74 | 0.77 | 0.43 | 0.00 |

Reading it honestly: with 27 questions, one question is about 0.04, so these differences are **within noise**. What the prototype does show is that character n-grams alone do not solve paraphrases or cross-lingual questions, and that the fused result is not worse than BM25. It is not evidence that this approach is "semantic".

### Revised options for the built-in backend

1. **SQLite FTS5 `trigram` tokenizer** as a second index (to be checked: it needs SQLite 3.34+, which recent Python builds ship). Fully built in, no vectors to store, no embed step; fuse with the word index by RRF. Likely the smallest change, but it is lexical fuzzy matching, not embeddings, so it would not use the explicit `embed` step.
2. **Hashed character n-gram vectors** stored by an explicit `embed` step. Sparse and larger than they look; only worth it if option 1 proves insufficient.
3. **Model-based embeddings** (Ollama first) for real semantic matching, explicit `embed --backend ollama --model ...`, optional.

### Revised plan

1. Harder, multilingual evaluation set (done in the same change as this update).
2. Prototype option 1 inside the repo on a branch and measure it on the evaluation set; decide whether it is worth shipping.
3. Embedding interface + Ollama backend + `embeddings` table + `embed` command, if real semantic search is still wanted.
4. Vector search + RRF behind `--mode`, tested with a fake embedder.
5. Documentation and evaluation numbers.

The evaluation set is still small and synthetic. Any result on it should be treated as a smoke test, not a benchmark; larger public datasets are welcome.

## Outcome

- **Built-in fuzzy option: measured, not shipped.** The FTS5 `trigram` index fused with BM25 (all character trigrams of the query, ORed) scored R@1 0.70 / MRR 0.77 against BM25's 0.70 / 0.76 on the 27-question set, with no gain on hard paraphrases (0.29) or cross-lingual questions (0.00): no meaningful difference, so it adds complexity for nothing.
- **Semantic search with Ollama: implemented.** `offline-rag embed` (explicit), `--mode vector|hybrid`, Ollama's `/api/embed`, vectors as float32 BLOBs in SQLite, brute-force cosine in pure Python, RRF with k = 60. No new dependencies. Remote hosts need `--allow-remote`.
- **Tested** with a fake embedder and a fake local Ollama HTTP server, which check the protocol and the plumbing. **Not tested with a real model**, so the quality gain is unmeasured; run `python -m offline_rag.eval --mode hybrid --model <model>` and compare with the baseline in `docs/EVALUATION.md`.
- **Not done:** OpenAI-compatible backends, query/document prefixes needed by some models, quantized or indexed vector search, and automatic embedding during `ingest` (declined: embedding stays an explicit step).
