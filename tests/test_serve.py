"""Tests for the local read-only web interface."""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from offline_rag import cli
from offline_rag.index import ingest
from offline_rag.serve import make_server


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
