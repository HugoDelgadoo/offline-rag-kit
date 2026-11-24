"""The bundled evaluation set must stay valid and keep a minimum BM25 baseline."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from offline_rag import eval as eval_cli
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

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eval_cli.main([
                "--corpus", str(ROOT / "eval" / "corpus"),
                "--questions", str(ROOT / "eval" / "questions.json"),
                *argv,
            ])
        return out.getvalue()

    def test_command_prints_table_and_json(self):
        table = self.run_main()
        self.assertIn("overall", table)
        self.assertIn("Not found in top 5", table)  # paraphrase questions BM25 cannot answer
        report = json.loads(self.run_main("--json"))
        self.assertEqual(report["overall"]["questions"], len(report["rows"]))

    def test_missing_questions_file_is_a_clean_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            eval_cli.main(["--questions", str(ROOT / "nope.json")])

    def test_semantic_modes_refuse_remote_hosts(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            eval_cli.main(["--mode", "hybrid", "--ollama-host", "example.com"])


if __name__ == "__main__":
    unittest.main()
