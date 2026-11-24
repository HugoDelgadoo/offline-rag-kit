"""`search --files`: one line per file with full path, match count and pages."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from offline_rag import cli
from offline_rag.index import ingest, search_files


class FilesTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.docs = root / "docs"
        (self.docs / "notes").mkdir(parents=True)
        self.db = root / "i.sqlite3"
        (self.docs / "notes" / "meeting.md").write_text(
            "We reviewed the vacation policy.\n\nThe retention policy was postponed.\n\nLunch is at noon.",
            encoding="utf-8",
        )
        (self.docs / "handbook.md").write_text("Our policy on remote work.", encoding="utf-8")
        (self.docs / "other.md").write_text("Nothing relevant here.", encoding="utf-8")
        with pymupdf.open() as doc:
            for text in ("Page one has the policy text.", "Page two is unrelated.", "Page three repeats policy."):
                doc.new_page().insert_text((72, 90), text)
            doc.save(self.docs / "contract.pdf")
        ingest(self.docs, self.db)


class SearchFilesTests(FilesTestBase):
    def test_each_file_once_with_count_pages_and_full_path(self):
        result = search_files("policy", self.db)
        self.assertEqual(result["match"], "all")
        self.assertEqual(result["total"], 3)
        by_name = {Path(f["path"]).name: f for f in result["files"]}
        self.assertEqual(set(by_name), {"meeting.md", "handbook.md", "contract.pdf"})
        self.assertEqual(by_name["meeting.md"]["matches"], 2)  # two passages mention it
        self.assertEqual(by_name["contract.pdf"]["pages"], [1, 3])
        self.assertEqual(by_name["meeting.md"]["pages"], [])
        self.assertEqual(Path(by_name["meeting.md"]["path"]), self.docs.resolve() / "notes" / "meeting.md")
        self.assertEqual(by_name["meeting.md"]["relative_path"], "notes/meeting.md")

    def test_requires_all_terms_then_falls_back_to_any(self):
        both = search_files("retention policy", self.db)
        self.assertEqual((both["match"], both["total"]), ("all", 1))
        fallback = search_files("retention vacation lunch zzz", self.db)  # no passage has all four
        self.assertEqual(fallback["match"], "any")
        self.assertEqual(fallback["total"], 1)  # only meeting.md contains any of them

    def test_limit_keeps_the_total(self):
        result = search_files("policy", self.db, limit=1)
        self.assertEqual((result["total"], len(result["files"])), (3, 1))

    def test_no_results_and_invalid_input(self):
        self.assertEqual(search_files("zzzz", self.db)["total"], 0)
        self.assertEqual(search_files("???", self.db), {"match": "all", "total": 0, "files": []})
        with self.assertRaises(ValueError):
            search_files("policy", self.db, limit=0)


class CliFilesTests(FilesTestBase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--db", str(self.db), *argv])
        return out.getvalue()

    def test_text_output_lists_files_with_paths_and_pages(self):
        text = self.run_cli("search", "policy", "--files")
        self.assertIn("3 files contain 'policy':", text)
        self.assertIn(str(self.docs.resolve() / "notes" / "meeting.md"), text)
        self.assertIn("2 matching passages", text)
        self.assertIn("pages 1, 3", text)

    def test_singular_forms_and_truncation_hint(self):
        self.assertIn("1 file contains 'retention policy':", self.run_cli("search", "retention policy", "--files"))
        self.assertIn("Showing the first 1 of 3", self.run_cli("search", "policy", "--files", "--limit", "1"))
        self.assertEqual(self.run_cli("search", "zzzz", "--files"), "No files found.\n")

    def test_fallback_is_explained(self):
        text = self.run_cli("search", "retention vacation zzz", "--files")
        self.assertIn("No file contains all the words", text)
        self.assertIn("1 file contains at least one of them", text)

    def test_json_output(self):
        data = json.loads(self.run_cli("--json", "search", "policy", "--files"))
        self.assertEqual((data["query"], data["total"], data["match"]), ("policy", 3, "all"))
        self.assertTrue(all({"path", "relative_path", "matches", "pages"} <= set(f) for f in data["files"]))

    def test_default_search_is_unchanged(self):
        self.assertIn("[1] ", self.run_cli("search", "policy"))

    def test_files_only_works_in_lexical_mode(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            self.run_cli("search", "policy", "--files", "--mode", "hybrid")
        self.assertIn("only works with --mode lexical", err.getvalue())


if __name__ == "__main__":
    unittest.main()
