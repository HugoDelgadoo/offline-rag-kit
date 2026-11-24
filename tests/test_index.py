"""Small, deterministic offline regression tests."""

import tempfile
import unittest
from pathlib import Path

import fitz

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
        self.assertEqual(ingest(self.docs, self.db), (1, 3))
        self.assertEqual(ingest(self.docs, self.db), (1, 3))
        results = search("SQLite", self.db)
        self.assertEqual(len(results), 1)
        self.assertIn("guide.md", citation(results[0]))
        self.assertIn("SQLite", results[0]["body"])
        self.assertEqual(search("???", self.db), [])

    def test_pdf_source_has_page_and_coordinates(self):
        path = self.docs / "example.pdf"
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 90), "Evidence in a PDF page")
            doc.save(path)
        ingest(self.docs, self.db)
        result = search("Evidence", self.db)[0]
        self.assertEqual(result["page"], 1)
        self.assertEqual(len(result["bbox"].split(",")), 4)
        self.assertIn("page 1", citation(result))


if __name__ == "__main__":
    unittest.main()
