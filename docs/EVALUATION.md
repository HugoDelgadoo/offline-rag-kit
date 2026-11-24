# Evaluation

`python -m offline_rag.eval` indexes `eval/corpus/` into a temporary database and runs every question in `eval/questions.json` through `search`. A result is relevant when it comes from the expected file and its passage contains the expected text. It reports recall@1/3/5 and mean reciprocal rank (MRR); add `--json` for machine-readable output.

The dataset is **small and synthetic** (11 documents in four languages, 27 questions). It was written for this project and is released under the repository's MIT license. It is a regression check and a way to compare retrieval ideas, not a benchmark: with so few questions, one question moves a score by about 0.04. Contributions of larger, public datasets are welcome.

Kinds of questions: `lexical` and `paraphrase` share some words with the answer; `hard-paraphrase` shares no content word; `multilingual` is answered in the same non-English language; `cross-lingual` asks in one language about a document in another.

## Baseline (BM25 with AND-then-OR fallback)

```text
subset         n     R@1     R@3     R@5     MRR
overall       27   0.704   0.815   0.852   0.762
cross-lingual   2   0.000   0.000   0.000   0.000
hard-paraphrase   7   0.286   0.714   0.714   0.476
lexical       10   1.000   1.000   1.000   1.000
multilingual   4   1.000   1.000   1.000   1.000
paraphrase     4   0.750   0.750   1.000   0.812
```

BM25 handles questions that share words with the answer, and fails on paraphrases and on questions asked in another language than the document. Those are the cases hybrid retrieval would have to improve (see `docs/DESIGN-hybrid-retrieval.md`).

## Evaluating semantic retrieval

```powershell
ollama pull bge-m3
python -m offline_rag.eval --mode hybrid --model bge-m3
python -m offline_rag.eval --mode vector --model bge-m3
```

These modes embed the bundled corpus with your local Ollama and print the same table. No results are recorded here yet because they depend on the model and have not been measured on a real model; please share yours in issue #4.
