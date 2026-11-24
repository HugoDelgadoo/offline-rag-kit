"""Tests for the local read-only web interface."""

import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

import pymupdf

from offline_rag import cli
from offline_rag.index import ingest, search
from offline_rag.serve import CONTEXT_POINTS, PreviewError, make_server, render_preview


class ServeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        docs = root / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("The retention policy keeps invoices for ten years", encoding="utf-8")
        (docs / "b.txt").write_text("<script>alert(1)</script> retention of logs", encoding="utf-8")
        self.db = root / "i.sqlite3"
        ingest(docs, self.db)
        self.before = self.db.read_bytes()
        self.server = make_server(self.db, 0)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, headers={"Host": host or f"127.0.0.1:{self.port}"})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_binds_to_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_home_page_and_security_headers(self):
        response, body = self.request("GET", "/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"offline-rag", body)
        self.assertIn("default-src 'none'", response.getheader("Content-Security-Policy"))
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")

    def test_page_never_uses_innerhtml(self):
        _, body = self.request("GET", "/")
        self.assertNotIn(b"innerHTML", body)

    def test_search_returns_passages(self):
        response, body = self.request("GET", "/api/search?q=retention+policy")
        data = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(data["results"][0]["path"], "a.md")
        self.assertIn("**retention**", data["results"][0]["snippet"])

    def test_files_view(self):
        _, body = self.request("GET", "/api/files?q=retention")
        self.assertEqual(json.loads(body)["total"], 2)

    def test_markup_in_documents_is_returned_as_plain_text(self):
        response, body = self.request("GET", "/api/search?q=alert")
        self.assertTrue(response.getheader("Content-Type").startswith("application/json"))
        self.assertIn("<script>", json.loads(body)["results"][0]["snippet"])

    def test_empty_and_overlong_queries_are_rejected(self):
        self.assertEqual(self.request("GET", "/api/search?q=")[0].status, 400)
        self.assertEqual(self.request("GET", "/api/search?q=" + "a" * 501)[0].status, 400)

    def test_foreign_host_header_is_refused(self):
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1"):
            self.assertEqual(self.request("GET", "/", host=host)[0].status, 403, host)
        self.assertEqual(self.request("GET", "/", host=f"localhost:{self.port}")[0].status, 200)

    def test_only_get_is_allowed(self):
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertEqual(self.request(method, "/api/search?q=x")[0].status, 405, method)

    def test_unknown_path_is_404(self):
        self.assertEqual(self.request("GET", "/etc/passwd")[0].status, 404)

    def test_index_is_not_modified(self):
        self.request("GET", "/api/search?q=retention")
        self.request("GET", "/api/files?q=retention")
        self.assertEqual(self.db.read_bytes(), self.before)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.docs = self.root / "docs"
        self.docs.mkdir()
        (self.docs / "notes.md").write_text("markdown about a quasar", encoding="utf-8")
        self.pdf = self.docs / "report.pdf"
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 100), "Quasar luminosity report", fontsize=14)
        document.save(self.pdf)
        document.close()
        self.db = self.root / "i.sqlite3"
        ingest(self.docs, self.db)
        self.hits = {h["path"]: h for h in search("quasar", self.db, 10)}
        self.pdf_before = self.pdf.read_bytes()

    def png(self, passage_id, full=False):
        data = render_preview(self.db, passage_id, full=full)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        return pymupdf.Pixmap(data)

    def assert_highlighted(self, pixmap, point):
        """The pixel is the yellow tint of the highlight, not white paper."""
        r, g, b = pixmap.pixel(int(point[0]), int(point[1]))[:3]
        self.assertGreater(r, 240)
        self.assertLess(b, 200)

    def test_pdf_preview_highlights_the_passage(self):
        hit = self.hits["report.pdf"]
        pixmap = self.png(hit["id"], full=True)
        x0, y0, _, _ = (float(n) for n in hit["bbox"].split(","))
        zoom = pixmap.width / 595.0  # A4 width in points
        self.assertAlmostEqual(pixmap.height / zoom, 842.0, delta=1)
        self.assert_highlighted(pixmap, ((x0 + 1) * zoom, (y0 + 1) * zoom))

    def test_default_preview_is_a_band_around_the_passage(self):
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 600), "Zeppelin hangar inspection notes", fontsize=14)
        document.save(self.docs / "tall.pdf")
        document.close()
        ingest(self.docs, self.db)
        hit = {h["path"]: h for h in search("zeppelin", self.db, 10)}["tall.pdf"]
        band = self.png(hit["id"])
        whole = self.png(hit["id"], full=True)
        self.assertEqual(band.width, whole.width)
        self.assertLess(band.height, whole.height / 2)
        x0, y0, _, _ = (float(n) for n in hit["bbox"].split(","))
        zoom = band.width / 595.0
        top = max(0.0, y0 - CONTEXT_POINTS)
        self.assert_highlighted(band, ((x0 + 1) * zoom, (y0 + 1 - top) * zoom))

    def test_rotated_page_keeps_the_highlight_on_the_text(self):
        document = pymupdf.open(self.pdf)
        document[0].set_rotation(90)
        document.save(self.root / "rot.pdf")
        document.close()
        (self.root / "rot.pdf").replace(self.pdf)
        ingest(self.docs, self.db)
        hit = {h["path"]: h for h in search("quasar", self.db, 10)}["report.pdf"]
        pixmap = self.png(hit["id"])  # rotated pages are always rendered whole
        x0, y0, _, _ = (float(n) for n in hit["bbox"].split(","))
        # 90 degrees clockwise: an unrotated point (x, y) lands at (page_height - y, x).
        zoom = pixmap.width / 842.0
        self.assert_highlighted(pixmap, ((842.0 - (y0 + 1)) * zoom, (x0 + 1) * zoom))

    def test_text_files_have_no_preview(self):
        with self.assertRaises(PreviewError) as raised:
            render_preview(self.db, self.hits["notes.md"]["id"])
        self.assertEqual(raised.exception.status, 404)

    def test_unknown_id_and_missing_file(self):
        with self.assertRaises(PreviewError) as raised:
            render_preview(self.db, 99999)
        self.assertEqual(raised.exception.status, 404)
        self.pdf.unlink()
        with self.assertRaises(PreviewError) as raised:
            render_preview(self.db, self.hits["report.pdf"]["id"])
        self.assertEqual(raised.exception.status, 404)

    def test_file_outside_the_indexed_folder_is_refused(self):
        (self.root / "secret.pdf").write_bytes(self.pdf.read_bytes())
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE passages SET path = ? WHERE path = 'report.pdf'", ("../secret.pdf",))
        with self.assertRaises(PreviewError) as raised:
            render_preview(self.db, self.hits["report.pdf"]["id"])
        self.assertEqual(raised.exception.status, 403)

    def test_changed_file_with_fewer_pages_is_a_clean_error(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE passages SET page = 7 WHERE path = 'report.pdf'")
        with self.assertRaises(PreviewError) as raised:
            render_preview(self.db, self.hits["report.pdf"]["id"])
        self.assertEqual(raised.exception.status, 404)

    def test_preview_never_modifies_the_pdf_or_the_index(self):
        index_before = self.db.read_bytes()
        self.png(self.hits["report.pdf"]["id"])
        self.assertEqual(self.pdf.read_bytes(), self.pdf_before)
        self.assertEqual(self.db.read_bytes(), index_before)

    def test_http_endpoint(self):
        server = make_server(self.db, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]

        def get(path):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
            response = connection.getresponse()
            body = response.read()
            connection.close()
            return response, body

        response, body = get(f"/preview?id={self.hits['report.pdf']['id']}")
        self.assertEqual((response.status, response.getheader("Content-Type")), (200, "image/png"))
        self.assertEqual(body[:4], b"\x89PNG")
        _, whole = get(f"/preview?id={self.hits['report.pdf']['id']}&full=1")
        self.assertLess(pymupdf.Pixmap(body).height, pymupdf.Pixmap(whole).height)
        for bad in ("/preview", "/preview?id=abc", "/preview?id=-1", "/preview?id=1;2", "/preview?id=%C2%B2"):
            self.assertEqual(get(bad)[0].status, 400, bad)
        self.assertEqual(get("/preview?id=99999")[0].status, 404)
        self.assertEqual(get("/api/search?q=quasar")[0].status, 200)


class ServeCommandTests(unittest.TestCase):
    def test_missing_index_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "none.sqlite3"
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--db", str(missing), "serve", "--port", "0"])
            self.assertEqual(raised.exception.code, 1)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
