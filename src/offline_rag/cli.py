"""Command line interface for offline document search."""

import argparse
import json
import sys

from .embeddings import DEFAULT_MODEL, embed_index, hybrid_search, indexed_model, ollama_embedder, vector_search
from .index import citation, ingest, search
from .ollama import answer_with_ollama


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="offline-rag", description="Search private documents entirely on your machine."
    )
    parser.add_argument("--db", default=".offline-rag/index.sqlite3", help="Local SQLite index path")
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON on stdout (errors stay on stderr)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ing = commands.add_parser("ingest", help="Index PDFs, .txt and .md files recursively")
    ing.add_argument("folder", help="Directory containing documents")

    emb = commands.add_parser(
        "embed", help="Create embeddings with local Ollama for semantic search (explicit, optional)"
    )
    emb.add_argument("--model", default=DEFAULT_MODEL, help="Ollama embedding model (ollama pull <model>)")
    emb.add_argument("--rebuild", action="store_true", help="Discard existing embeddings first")
    emb.add_argument("--ollama-host", help="Ollama URL (default: $OLLAMA_HOST or 127.0.0.1:11434)")
    emb.add_argument("--allow-remote", action="store_true", help="Allow a non-loopback Ollama host")

    for command in ("search", "ask"):
        sub = commands.add_parser(command, help="Search locally" if command == "search" else "Ask local Ollama")
        sub.add_argument("query", help="Question or search terms")
        sub.add_argument("--limit", type=int, default=5)
        sub.add_argument(
            "--mode", choices=("lexical", "vector", "hybrid"), default="lexical",
            help="lexical (default, offline); vector/hybrid need 'offline-rag embed' and a running Ollama",
        )
        sub.add_argument("--ollama-host", help="Ollama URL (default: $OLLAMA_HOST or 127.0.0.1:11434)")
        sub.add_argument(
            "--allow-remote", action="store_true",
            help="Allow a non-loopback Ollama host (text is sent to it)",
        )
        if command == "ask":
            sub.add_argument("--model", default="llama3.2", help="Ollama model used to write the answer")
    return parser


def _hit_json(rank: int, hit: dict) -> dict:
    return {
        "rank": rank,
        "citation": citation(hit),
        "path": hit["path"],
        "page": hit["page"] or None,
        "bbox": [float(n) for n in hit["bbox"].split(",")] if hit["bbox"] else None,
        "score": hit["score"],
        "snippet": hit["snippet"],
        "text": hit["body"],
    }


def _dump(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _retrieve(args) -> list[dict]:
    if args.mode == "lexical":
        return search(args.query, args.db, args.limit)
    model = indexed_model(args.db)
    if model is None:
        raise ValueError("This index has no embeddings. Run 'offline-rag embed' first.")
    embedder = ollama_embedder(model, args.ollama_host, args.allow_remote)
    run = vector_search if args.mode == "vector" else hybrid_search
    return run(args.query, args.db, embedder, args.limit)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ingest":
            result = ingest(args.folder, args.db)
            skipped = [{"path": str(p), "error": message} for p, message in result.skipped]
            if args.json:
                _dump({
                    "files": result.files, "passages": result.passages,
                    "unchanged": result.unchanged, "database": args.db, "skipped": skipped,
                })
            else:
                for item in skipped:
                    print(f"Warning: skipped {item['path']}: {item['error']}", file=sys.stderr)
                print(
                    f"Indexed {result.files} files ({result.unchanged} unchanged) and "
                    f"{result.passages} passages in {args.db}"
                )
        elif args.command == "embed":
            embedder = ollama_embedder(args.model, args.ollama_host, args.allow_remote)
            count = embed_index(args.db, embedder, args.model, rebuild=args.rebuild)
            if args.json:
                _dump({"embedded": count, "model": args.model, "database": args.db})
            else:
                print(f"Embedded {count} passages with {args.model} in {args.db}")
        else:
            hits = _retrieve(args)
            if args.command == "search":
                if args.json:
                    _dump({"query": args.query, "results": [_hit_json(i, h) for i, h in enumerate(hits, 1)]})
                else:
                    if not hits:
                        print("No matching passages found.")
                    for rank, hit in enumerate(hits, start=1):
                        print(f"\n[{rank}] {citation(hit)}\n{hit['snippet']}")
            else:
                answer = answer_with_ollama(
                    args.query, hits, model=args.model,
                    host=args.ollama_host, allow_remote=args.allow_remote,
                )
                if args.json:
                    _dump({
                        "question": args.query,
                        "model": args.model,
                        "answer": answer,
                        "sources": [_hit_json(i, h) for i, h in enumerate(hits, 1)],
                    })
                else:
                    print(answer)
                    if hits:
                        print("\nRetrieved evidence:")
                        for rank, hit in enumerate(hits, start=1):
                            print(f"[{rank}] {citation(hit)}")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
