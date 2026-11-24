"""The bundled evaluation set must stay valid and keep a minimum BM25 baseline."""

import json
import unittest
from pathlib import Path

from offline_rag.eval import evaluate

ROOT = Path(__file__).resolve().parent.parent


class EvalTests(unittest.TestCase):
    def test_bundled_dataset_is_consistent_and_meets_baseline(self):
        corpus = ROOT / "eval" / "corpus"
        questions = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))["questions"]
        for item in questions:  # every expected passage really exists in the corpus
            text = (corpus / item["path"]).read_text(encoding="utf-8").lower()
            self.assertIn(item["contains"].lower(), text, item["q"])
        report = evaluate(corpus, questions)
        # Word-overlap questions must keep working; paraphrase / cross-lingual kinds are
        # tracked in docs/EVALUATION.md but are expected to be weak for lexical search.
        for kind in ("lexical", "multilingual"):
            self.assertGreaterEqual(report["by_kind"][kind]["mrr"], 0.9, kind)
        self.assertGreaterEqual(report["overall"]["recall@5"], 0.8)


if __name__ == "__main__":
    unittest.main()
