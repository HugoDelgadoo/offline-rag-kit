"""Ollama host resolution and request tests (no real network)."""

import io
import json
import os
import unittest
from unittest import mock

from offline_rag import ollama

PASSAGES = [{"path": "a.md", "page": 0, "bbox": "", "body": "SQLite is local."}]


class ResolveHostTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("OLLAMA_HOST", None)

    def test_default_is_loopback(self):
        self.assertEqual(ollama.resolve_host(), "http://127.0.0.1:11434")

    def test_env_and_formats(self):
        cases = {
            "localhost": "http://localhost:11434",
            "127.0.0.1:9999": "http://127.0.0.1:9999",
            "http://[::1]:11434": "http://[::1]:11434",
            "0.0.0.0:11434": "http://127.0.0.1:11434",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                os.environ["OLLAMA_HOST"] = value
                self.assertEqual(ollama.resolve_host(), expected)

    def test_explicit_host_beats_env(self):
        os.environ["OLLAMA_HOST"] = "localhost:1"
        self.assertEqual(ollama.resolve_host("127.0.0.1:2"), "http://127.0.0.1:2")

    def test_remote_hosts_are_refused_unless_allowed(self):
        for value in ("example.com", "http://192.168.1.20:11434", "10.0.0.5"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "non-loopback"):
                    ollama.resolve_host(value)
        self.assertEqual(ollama.resolve_host("192.168.1.20", allow_remote=True), "http://192.168.1.20:11434")

    def test_invalid_scheme(self):
        with self.assertRaises(ValueError):
            ollama.resolve_host("ftp://localhost")


class AnswerTests(unittest.TestCase):
    def test_request_goes_to_resolved_host(self):
        response = io.BytesIO(json.dumps({"response": "ok [1]"}).encode())
        with mock.patch.object(ollama, "urlopen", return_value=response) as urlopen:
            self.assertEqual(ollama.answer_with_ollama("q?", PASSAGES, host="localhost:5555"), "ok [1]")
        self.assertEqual(urlopen.call_args.args[0].full_url, "http://localhost:5555/api/generate")

    def test_remote_host_refused_before_any_request(self):
        with mock.patch.object(ollama, "urlopen") as urlopen:
            with self.assertRaises(ValueError):
                ollama.answer_with_ollama("q?", PASSAGES, host="example.com")
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
