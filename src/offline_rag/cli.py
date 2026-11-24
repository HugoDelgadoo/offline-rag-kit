"""Command line interface for offline document search."""

import argparse
import json
import sys

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

    for command in ("search", "ask"):
        sub = commands.add_parser(command, help="Search locally" if command == "search" else "Ask local Ollama")
        sub.add_argument("query", help="Question or search terms")
        sub.add_argument("--limit", type=int, default=5)
        if command == "ask":
            sub.add_argument("--model", default="llama3.2", help="Ollama model installed locally")
    return parser


def _hit_json(rank: int, hit: dict) -> dict:
    return {
        "rank": rank,
        "citation": citation(hit),
        "path": hit["path"],
        "page": hit["page"] or None,
        "bbox": [float(n) for n in hit["bbox"].split(",")] if hit["bbox"] else None,
        "score": hit["score"],
        "text": hit["body"],
    }


def _dump(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ingest":
            skipped = []

            def warn(path, exc):
                skipped.append({"path": str(path), "error": str(exc)})
                if not args.json:
                    print(f"Warning: skipped {path}: {exc}", file=sys.stderr)

            files, passages = ingest(args.folder, args.db, on_error=warn)
            if args.json:
                _dump({"files": files, "passages": passages, "database": args.db, "skipped": skipped})
            else:
                print(f"Indexed {files} files and {passages} passages in {args.db}")
        else:
            hits = search(args.query, args.db, args.limit)
            if args.command == "search":
                if args.json:
                    _dump({"query": args.query, "results": [_hit_json(i, h) for i, h in enumerate(hits, 1)]})
                else:
                    if not hits:
                        print("No matching passages found.")
                    for rank, hit in enumerate(hits, start=1):
                        print(f"\n[{rank}] {citation(hit)}\n{hit['body'][:700]}")
            else:
                answer = answer_with_ollama(args.query, hits, model=args.model)
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
