# Evaluation

`python -m offline_rag.eval` indexes `eval/corpus/` into a temporary database and runs every question in `eval/questions.json` through `search`. A result is relevant when it comes from the expected file and its passage contains the expected text. It reports recall@1/3/5 and mean reciprocal rank (MRR); add `--json` for machine-readable output.

The dataset is **small and synthetic** (6 documents, 14 questions). It was written for this project and is released under the repository's MIT license. It is a regression check and a starting point, not a proof of quality: the "paraphrase" questions are only partly paraphrased and still share incidental words with their answers. Contributions of larger, public datasets are welcome (see the roadmap).

## Baseline (v0.1, BM25 with AND-then-OR fallback)

```text
subset         n     R@1     R@3     R@5     MRR
overall       14   0.929   0.929   1.000   0.946
lexical       10   1.000   1.000   1.000   1.000
paraphrase     4   0.750   0.750   1.000   0.812
```
