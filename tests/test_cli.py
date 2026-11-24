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
        self.assertEqual((data["files"], data["passages"], data["unchanged"]), (1, 1, 0))
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
        self.assertIn("**SQLite**", hit["snippet"])

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


class DefaultDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def env(self, **extra):
        return mock.patch.dict(
            "os.environ",
            {"LOCALAPPDATA": str(self.root / "local"), "XDG_DATA_HOME": str(self.root / "xdg"),
             "HOME": str(self.root), "USERPROFILE": str(self.root), **extra},
        )

    def test_explicit_db_wins(self):
        with self.env(OFFLINE_RAG_DB=str(self.root / "env.sqlite3")):
            self.assertEqual(cli.resolve_db("x.sqlite3"), "x.sqlite3")

    def test_env_variable_overrides_default(self):
        with self.env(OFFLINE_RAG_DB=str(self.root / "env.sqlite3")):
            self.assertEqual(cli.resolve_db(None), str(self.root / "env.sqlite3"))

    def test_default_is_fixed_and_independent_of_cwd(self):
        with self.env():
            first = cli.resolve_db(None)
            self.assertTrue(Path(first).is_absolute())
            self.assertEqual(Path(first).name, "index.sqlite3")
            self.assertEqual(Path(first).parent.name, "offline-rag")
            self.assertTrue(str(self.root) in first)

    def test_legacy_local_index_is_used_with_a_hint(self):
        with self.env(), mock.patch.object(cli, "LEGACY_DB", self.root / "legacy.sqlite3"):
            (self.root / "legacy.sqlite3").write_bytes(b"")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(cli.resolve_db(None), str(self.root / "legacy.sqlite3"))
            self.assertIn("New default location", err.getvalue())

    def test_fixed_index_beats_legacy(self):
        with self.env(), mock.patch.object(cli, "LEGACY_DB", self.root / "legacy.sqlite3"):
            (self.root / "legacy.sqlite3").write_bytes(b"")
            fixed = cli.default_db_path()
            fixed.parent.mkdir(parents=True)
            fixed.write_bytes(b"")
            self.assertEqual(cli.resolve_db(None), str(fixed))
