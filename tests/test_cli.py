"""CLI tests, including machine-readable --json output."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from offline_rag import cli


class CliJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.docs = root / "docs"
        self.docs.mkdir()
        (self.docs / "a.md").write_text("Ünïcode text about SQLite storage", encoding="utf-8")
        (self.docs / "bad.pdf").write_bytes(b"nope")
        self.db = str(root / "i.sqlite3")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(list(argv))
        return out.getvalue(), err.getvalue()

    def test_ingest_json_reports_skipped_files_without_stderr_noise(self):
        out, err = self.run_cli("--db", self.db, "--json", "ingest", str(self.docs))
        data = json.loads(out)
        self.assertEqual((data["files"], data["passages"]), (1, 1))
        self.assertEqual([Path(s["path"]).name for s in data["skipped"]], ["bad.pdf"])
        self.assertEqual(err, "")

    def test_search_json_is_valid_and_complete(self):
        self.run_cli("--db", self.db, "ingest", self.docs.as_posix())
        out, _ = self.run_cli("--db", self.db, "--json", "search", "sqlite")
        data = json.loads(out)
        hit = data["results"][0]
        self.assertEqual(hit["rank"], 1)
        self.assertEqual(hit["citation"], "a.md")
        self.assertIsNone(hit["page"])
        self.assertIsNone(hit["bbox"])
        self.assertIn("Ünïcode", hit["text"])

    def test_search_json_without_hits_is_empty_list(self):
        self.run_cli("--db", self.db, "ingest", self.docs.as_posix())
        out, _ = self.run_cli("--db", self.db, "--json", "search", "zzzz")
        self.assertEqual(json.loads(out)["results"], [])

    def test_ask_json_includes_answer_and_sources(self):
        self.run_cli("--db", self.db, "ingest", self.docs.as_posix())
        with mock.patch.object(cli, "answer_with_ollama", return_value="It uses SQLite [1]."):
            out, _ = self.run_cli("--db", self.db, "--json", "ask", "storage?", "--model", "m")
        data = json.loads(out)
        self.assertEqual(data["answer"], "It uses SQLite [1].")
        self.assertEqual(data["model"], "m")
        self.assertEqual(len(data["sources"]), 1)

    def test_error_exits_nonzero_and_keeps_stdout_empty(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--db", self.db, "--json", "ingest", "/does/not/exist"])
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("Error:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
