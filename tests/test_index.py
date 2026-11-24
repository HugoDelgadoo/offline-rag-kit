"""Small, deterministic offline regression tests."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf

from offline_rag.index import citation, ingest, search


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.docs = self.root / "docs"
        self.docs.mkdir()
        self.db = self.root / "test.sqlite3"

    def test_text_retrieval_and_repeat_ingest(self):
        (self.docs / "guide.md").write_text(
            "# Setup\n\nThe deployment uses local SQLite storage.\n\nSensitive PDFs stay offline.",
            encoding="utf-8",
        )
        first = ingest(self.docs, self.db)
        self.assertEqual((first.files, first.passages, first.unchanged), (1, 3, 0))
        second = ingest(self.docs, self.db)
        self.assertEqual((second.files, second.passages, second.unchanged), (1, 3, 1))
        results = search("SQLite", self.db)
        self.assertEqual(len(results), 1)
        self.assertIn("guide.md", citation(results[0]))
        self.assertIn("SQLite", results[0]["body"])
        self.assertEqual(search("???", self.db), [])

    def test_pdf_source_has_page_and_coordinates(self):
        path = self.docs / "example.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 90), "Evidence in a PDF page")
            doc.save(path)
        ingest(self.docs, self.db)
        result = search("Evidence", self.db)[0]
        self.assertEqual(result["page"], 1)
        self.assertEqual(len(result["bbox"].split(",")), 4)
        self.assertIn("page 1", citation(result))

    def test_removed_files_are_dropped_on_reingest(self):
        keep, gone = self.docs / "keep.md", self.docs / "gone.md"
        keep.write_text("alpha topic", encoding="utf-8")
        gone.write_text("beta topic", encoding="utf-8")
        ingest(self.docs, self.db)
        self.assertEqual(len(search("beta", self.db)), 1)
        gone.unlink()
        result = ingest(self.docs, self.db)
        self.assertEqual((result.files, result.passages), (1, 1))
        self.assertEqual(search("beta", self.db), [])
        self.assertEqual(len(search("alpha", self.db)), 1)

    def test_stale_cleanup_ignores_other_folders(self):
        other = self.root / "other"
        other.mkdir()
        (other / "o.md").write_text("gamma topic", encoding="utf-8")
        (self.docs / "d.md").write_text("delta topic", encoding="utf-8")
        ingest(other, self.db)
        ingest(self.docs, self.db)
        self.assertEqual(len(search("gamma", self.db)), 1)

    def test_broken_files_are_skipped_and_reported(self):
        (self.docs / "good.md").write_text("good content", encoding="utf-8")
        (self.docs / "broken.pdf").write_bytes(b"not a real pdf")
        (self.docs / "latin.txt").write_bytes("caf\xe9".encode("latin-1"))
        result = ingest(self.docs, self.db)
        self.assertEqual((result.files, result.passages), (1, 1))
        self.assertCountEqual([p.name for p, _ in result.skipped], ["broken.pdf", "latin.txt"])
        self.assertEqual(len(search("good", self.db)), 1)

    def test_all_terms_rank_before_partial_matches(self):
        (self.docs / "a.md").write_text(
            "local local local local search\n\nlocal search engine for private documents",
            encoding="utf-8",
        )
        (self.docs / "b.md").write_text("search search search search", encoding="utf-8")
        ingest(self.docs, self.db)
        results = search("private search", self.db, limit=5)
        self.assertIn("private", results[0]["body"])  # contains both terms
        self.assertGreater(len(results), 1)  # partial matches fill the rest
        self.assertEqual(len({r["body"] for r in results}), len(results))  # no duplicates

    def test_and_only_when_enough_results(self):
        (self.docs / "a.md").write_text("red apple\n\nred car\n\napple pie", encoding="utf-8")
        ingest(self.docs, self.db)
        results = search("red apple", self.db, limit=1)
        self.assertEqual(results[0]["body"], "red apple")
        self.assertEqual(len(results), 1)

    def test_repeated_terms_and_operators_are_safe(self):
        (self.docs / "a.md").write_text("sqlite sqlite storage", encoding="utf-8")
        ingest(self.docs, self.db)
        self.assertEqual(len(search("sqlite sqlite NOT AND OR storage", self.db)), 1)

    def test_citations_use_paths_relative_to_ingested_folder(self):
        (self.docs / "sub").mkdir()
        (self.docs / "sub" / "deep.md").write_text("nested note", encoding="utf-8")
        ingest(self.docs, self.db)
        hit = search("nested", self.db)[0]
        self.assertEqual(hit["path"], "sub/deep.md")
        self.assertEqual(citation(hit), "sub/deep.md")
        self.assertNotIn(self.tmp.name, hit["path"])

    def test_moving_the_folder_does_not_duplicate_passages(self):
        (self.docs / "note.md").write_text("portable knowledge", encoding="utf-8")
        ingest(self.docs, self.db)
        moved = self.root / "moved"
        self.docs.rename(moved)
        ingest(moved, self.db)
        self.assertEqual(len(search("portable", self.db)), 1)

    def test_old_absolute_path_index_gives_clear_error(self):
        import sqlite3

        with sqlite3.connect(self.db) as old:
            old.execute("CREATE VIRTUAL TABLE passages USING fts5(path UNINDEXED, page UNINDEXED, bbox UNINDEXED, body)")
        old.close()
        with self.assertRaisesRegex(ValueError, "older version"):
            search("anything", self.db)

    def test_snippet_shows_match_far_from_start(self):
        filler = " ".join(f"word{i}" for i in range(300))
        (self.docs / "long.md").write_text(f"{filler} needle {filler}", encoding="utf-8")
        ingest(self.docs, self.db)
        hit = search("needle", self.db)[0]
        self.assertIn("**needle**", hit["snippet"])
        self.assertLess(len(hit["snippet"]), len(hit["body"]))

    def test_unchanged_files_are_not_reparsed(self):
        (self.docs / "a.md").write_text("stable text", encoding="utf-8")
        ingest(self.docs, self.db)
        with mock.patch("offline_rag.index.extract_passages", side_effect=AssertionError("re-parsed")):
            result = ingest(self.docs, self.db)
        self.assertEqual((result.files, result.unchanged, result.passages), (1, 1, 1))

    def test_changed_content_is_reindexed_even_with_same_size_and_mtime(self):
        path = self.docs / "a.md"
        path.write_text("first version", encoding="utf-8")
        ingest(self.docs, self.db)
        stat = path.stat()
        path.write_text("other version", encoding="utf-8")  # same length
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        result = ingest(self.docs, self.db)
        self.assertEqual(result.unchanged, 0)
        self.assertEqual(search("first", self.db), [])
        self.assertEqual(len(search("other", self.db)), 1)

    def test_touched_but_identical_file_stays_unchanged(self):
        path = self.docs / "a.md"
        path.write_text("same bytes", encoding="utf-8")
        ingest(self.docs, self.db)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.assertEqual(ingest(self.docs, self.db).unchanged, 1)

    def test_failed_reparse_keeps_previous_passages(self):
        path = self.docs / "a.md"
        path.write_text("keep me", encoding="utf-8")
        ingest(self.docs, self.db)
        path.write_bytes("caf\xe9 changed".encode("latin-1"))
        result = ingest(self.docs, self.db)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(len(search("keep", self.db)), 1)


if __name__ == "__main__":
    unittest.main()
