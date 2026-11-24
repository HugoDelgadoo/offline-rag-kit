"""Semantic retrieval tests with a fake embedder (no Ollama needed)."""

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from offline_rag import cli, embeddings
from offline_rag.embeddings import embed_index, hybrid_search, indexed_model, ollama_embedder, vector_search
from offline_rag.index import ingest, search

# Toy "semantic" space: words from the same group map to the same axis, so synonyms match.
GROUPS = [
    {"remote", "home", "telework", "teletrabajo"},
    {"vacation", "holiday", "leave", "vacaciones"},
    {"password", "credential", "contraseña"},
    {"invoice", "bill"},
]


def fake_embedder(texts):
    vectors = []
    for text in texts:
        words = {w.strip(".,?¿¡!").lower() for w in text.split()}
        vector = [1.0 if words & group else 0.0 for group in GROUPS]
        vector.append(0.05)  # keeps vectors non-zero for unrelated text
        vectors.append(vector)
    return vectors


class EmbeddingTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.docs = root / "docs"
        self.docs.mkdir()
        self.db = root / "i.sqlite3"
        (self.docs / "wfh.md").write_text("Telework is allowed three days a week.", encoding="utf-8")
        (self.docs / "leave.md").write_text("Holiday requests need fifteen days of notice.", encoding="utf-8")
        (self.docs / "pw.md").write_text("Credential sharing is forbidden.", encoding="utf-8")
        ingest(self.docs, self.db)

    def count(self, table):
        with closing(sqlite3.connect(self.db)) as c:
            return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class EmbedIndexTests(EmbeddingTestBase):
    def test_embeds_all_passages_once_and_incrementally(self):
        self.assertEqual(embed_index(self.db, fake_embedder, "toy"), 3)
        self.assertEqual(embed_index(self.db, fake_embedder, "toy"), 0)  # nothing new
        (self.docs / "bill.md").write_text("Every invoice is archived.", encoding="utf-8")
        ingest(self.docs, self.db)
        self.assertEqual(embed_index(self.db, fake_embedder, "toy"), 1)
        self.assertEqual(indexed_model(self.db), "toy")

    def test_switching_model_requires_rebuild(self):
        embed_index(self.db, fake_embedder, "toy")
        with self.assertRaisesRegex(ValueError, "--rebuild"):
            embed_index(self.db, fake_embedder, "other")
        self.assertEqual(embed_index(self.db, fake_embedder, "other", rebuild=True), 3)
        self.assertEqual(indexed_model(self.db), "other")

    def test_reindexing_or_deleting_files_removes_their_vectors(self):
        embed_index(self.db, fake_embedder, "toy")
        (self.docs / "wfh.md").write_text("Telework changed text.", encoding="utf-8")
        (self.docs / "pw.md").unlink()
        ingest(self.docs, self.db)
        self.assertEqual(self.count("embeddings"), 1)  # only leave.md keeps its vector
        self.assertEqual(embed_index(self.db, fake_embedder, "toy"), 1)  # the changed file
        self.assertEqual(self.count("embeddings"), self.count("passages"))

    def test_vectors_of_different_sizes_are_rejected(self):
        sizes = iter([[1.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0]])
        with self.assertRaisesRegex(ValueError, "different sizes"):
            embed_index(self.db, lambda texts: [next(sizes) for _ in texts], "toy", batch_size=1)


class SearchTests(EmbeddingTestBase):
    def setUp(self):
        super().setUp()
        embed_index(self.db, fake_embedder, "toy")

    def test_vector_search_finds_synonyms_that_bm25_misses(self):
        self.assertEqual(search("remote", self.db), [])  # no shared word with the passage
        hit = vector_search("remote", self.db, fake_embedder, limit=1)[0]
        self.assertEqual(hit["path"], "wfh.md")
        self.assertGreater(hit["score"], 0.9)

    def test_hybrid_keeps_lexical_matches_and_adds_semantic_ones(self):
        (self.docs / "extra.md").write_text("Retention schedule for logs.", encoding="utf-8")
        ingest(self.docs, self.db)
        embed_index(self.db, fake_embedder, "toy")
        by_lexical = hybrid_search("retention", self.db, fake_embedder, limit=3)
        self.assertEqual(by_lexical[0]["path"], "extra.md")  # exact word still wins
        by_meaning = hybrid_search("holiday", self.db, fake_embedder, limit=1)
        self.assertEqual(by_meaning[0]["path"], "leave.md")
        paths = [h["path"] for h in hybrid_search("remote", self.db, fake_embedder, limit=3)]
        self.assertEqual(paths[0], "wfh.md")
        self.assertEqual(len(paths), len(set(paths)))  # fused list has no duplicates

    def test_vector_search_without_embeddings_explains_what_to_do(self):
        other = Path(self.tmp.name) / "plain.sqlite3"
        ingest(self.docs, other)
        with self.assertRaisesRegex(ValueError, "offline-rag embed"):
            vector_search("x", other, fake_embedder)

    def test_query_with_wrong_dimension_is_reported(self):
        with self.assertRaisesRegex(ValueError, "model changed"):
            vector_search("x", self.db, lambda texts: [[1.0, 0.0]])


class OllamaProtocolTests(unittest.TestCase):
    def response(self, payload):
        return io.BytesIO(json.dumps(payload).encode())

    def test_posts_to_api_embed_and_returns_vectors(self):
        with mock.patch.object(embeddings, "urlopen", return_value=self.response({"embeddings": [[1, 0], [0, 1]]})) as urlopen:
            vectors = ollama_embedder("bge-m3", host="localhost:5555")(["a", "b"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:5555/api/embed")
        body = json.loads(request.data)
        self.assertEqual((body["model"], body["input"]), ("bge-m3", ["a", "b"]))
        self.assertEqual(vectors, [[1, 0], [0, 1]])

    def test_remote_host_refused_before_any_request(self):
        with mock.patch.object(embeddings, "urlopen") as urlopen:
            with self.assertRaisesRegex(ValueError, "non-loopback"):
                ollama_embedder("m", host="example.com")
        urlopen.assert_not_called()

    def test_errors_are_actionable(self):
        with mock.patch.object(embeddings, "urlopen", side_effect=URLError("refused")):
            with self.assertRaisesRegex(RuntimeError, "ollama serve"):
                ollama_embedder("m")(["a"])
        not_found = HTTPError("u", 404, "nf", {}, io.BytesIO(b'{"error": "model not found"}'))
        with mock.patch.object(embeddings, "urlopen", side_effect=not_found):
            with self.assertRaisesRegex(RuntimeError, "ollama pull m"):
                ollama_embedder("m")(["a"])

    def test_malformed_response_is_rejected(self):
        for bad in ({}, {"embeddings": [[1.0]]}, {"embeddings": [[]]}):
            with self.subTest(bad=bad):
                with mock.patch.object(embeddings, "urlopen", return_value=self.response(bad)):
                    with self.assertRaisesRegex(RuntimeError, "Unexpected response"):
                        ollama_embedder("m")(["a", "b"])


class CliTests(EmbeddingTestBase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(cli, "ollama_embedder", return_value=fake_embedder):
            cli.main(["--db", str(self.db), *argv])
        return out.getvalue()

    def test_embed_then_semantic_search_and_json(self):
        self.assertIn("Embedded 3 passages with toy", self.run_cli("embed", "--model", "toy"))
        data = json.loads(self.run_cli("--json", "search", "remote", "--mode", "hybrid", "--limit", "1"))
        self.assertEqual(data["results"][0]["citation"], "wfh.md")
        self.assertEqual(self.run_cli("search", "remote"), "No matching passages found.\n")  # default stays lexical

    def test_vector_mode_without_embeddings_fails_clearly(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            self.run_cli("search", "remote", "--mode", "vector")
        self.assertIn("offline-rag embed", err.getvalue())


if __name__ == "__main__":
    unittest.main()
