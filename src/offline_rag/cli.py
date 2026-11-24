"""Command line interface for offline document search."""

import argparse
import sys

from .index import citation, ingest, search
from .ollama import answer_with_ollama


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="offline-rag", description="Search private documents entirely on your machine."
    )
    parser.add_argument("--db", default=".offline-rag/index.sqlite3", help="Local SQLite index path")
    commands = parser.add_subparsers(dest="command", required=True)

    ing = commands.add_parser("ingest", help="Index PDFs, .txt and .md files recursively")
    ing.add_argument("folder", help="Directory containing documents")

    for command in ("search", "ask"):
        sub = commands.add_parser(command, help="Search locally" if command == "search" else "Ask local Ollama")
        sub.add_argument("query", help="Question or search terms")
        sub.add_argument("--limit", type=int, default=5)
        if command == "ask":
            sub.add_argument("--model", default="llama3.2", help="Ollama model installed locally")

    args = parser.parse_args()
    try:
        if args.command == "ingest":
            def warn(path, exc):
                print(f"Warning: skipped {path}: {exc}", file=sys.stderr)

            files, passages = ingest(args.folder, args.db, on_error=warn)
            print(f"Indexed {files} files and {passages} passages in {args.db}")
        else:
            hits = search(args.query, args.db, args.limit)
            if args.command == "search":
                if not hits:
                    print("No matching passages found.")
                for rank, hit in enumerate(hits, start=1):
                    print(f"\n[{rank}] {citation(hit)}\n{hit['body'][:700]}")
            else:
                print(answer_with_ollama(args.query, hits, model=args.model))
                if hits:
                    print("\nRetrieved evidence:")
                    for rank, hit in enumerate(hits, start=1):
                        print(f"[{rank}] {citation(hit)}")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
