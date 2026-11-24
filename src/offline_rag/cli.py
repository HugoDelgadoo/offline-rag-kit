"""Command line interface for offline document search."""

import argparse
import json
import os
import sys
from pathlib import Path

from .embeddings import DEFAULT_MODEL, embed_index, hybrid_search, indexed_model, ollama_embedder, vector_search
from .index import citation, ingest, search, search_files
from .ollama import answer_with_ollama

LEGACY_DB = Path(".offline-rag") / "index.sqlite3"


def default_db_path() -> Path:
    """Fixed per-user index location, so the index does not depend on the current directory."""
    override = os.environ.get("OFFLINE_RAG_DB")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "offline-rag" / "index.sqlite3"


def resolve_db(explicit: str | None) -> str:
    """--db wins, then $OFFLINE_RAG_DB, then the fixed folder. A pre-0.1.5 index in the current
    folder is still used (with a hint) until a fixed-location index exists."""
    if explicit:
        return explicit
    fixed = default_db_path()
    if not os.environ.get("OFFLINE_RAG_DB") and not fixed.exists() and LEGACY_DB.exists():
        print(
            f"Using the index in this folder ({LEGACY_DB}). New default location: {fixed}. "
            f"Move the file there, or pass --db, to use it from any folder.",
            file=sys.stderr,
        )
        return str(LEGACY_DB)
    return str(fixed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="offline-rag", description="Search private documents entirely on your machine."
    )
    parser.add_argument(
        "--db", default=None,
        help="Local SQLite index path (default: $OFFLINE_RAG_DB, or a fixed per-user folder; see README)",
    )
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

    srv = commands.add_parser("serve", help="Open a local, read-only web interface (127.0.0.1 only)")
    srv.add_argument("--port", type=int, default=8765, help="Port on 127.0.0.1 (default: 8765, 0 = any free port)")
    srv.add_argument("--open", action="store_true", help="Open the page in your default browser")

    for command in ("search", "ask"):
        sub = commands.add_parser(command, help="Search locally" if command == "search" else "Ask local Ollama")
        sub.add_argument("query", help="Question or search terms")
        sub.add_argument(
            "--limit", type=int, default=None,
            help="Maximum results (default: 5 passages, or 20 files with --files)",
        )
        sub.add_argument(
            "--mode", choices=("lexical", "vector", "hybrid"), default="lexical",
            help="lexical (default, offline); vector/hybrid need 'offline-rag embed' and a running Ollama",
        )
        sub.add_argument("--ollama-host", help="Ollama URL (default: $OLLAMA_HOST or 127.0.0.1:11434)")
        sub.add_argument(
            "--allow-remote", action="store_true",
            help="Allow a non-loopback Ollama host (text is sent to it)",
        )
        if command == "search":
            sub.add_argument(
                "--files", action="store_true",
                help="List the files that contain the terms (full path, matches, pages) instead of passages",
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


def _format_pages(pages: list[int], shown: int = 10) -> str:
    text = ", ".join(str(p) for p in pages[:shown])
    return text + (f", … (+{len(pages) - shown})" if len(pages) > shown else "")


def _print_files(query: str, result: dict) -> None:
    total = result["total"]
    if not total:
        print("No files found.")
        return
    noun, verb = ("file", "contains") if total == 1 else ("files", "contain")
    if result["match"] == "any":
        print(f"No file contains all the words of {query!r}; {total} {noun} {verb} at least one of them:")
    else:
        print(f"{total} {noun} {verb} {query!r}:")
    for item in result["files"]:
        count = item["matches"]
        detail = f"{count} matching passage{'s' if count != 1 else ''}"
        if item["pages"]:
            detail += f"; page{'s' if len(item['pages']) != 1 else ''} {_format_pages(item['pages'])}"
        print(f"  {item['path']}  ({detail})")
    if total > len(result["files"]):
        print(f"Showing the first {len(result['files'])} of {total}. Use --limit to see more (up to 100).")


def _retrieve(args) -> list[dict]:
    limit = args.limit if args.limit is not None else 5
    if args.mode == "lexical":
        return search(args.query, args.db, limit)
    model = indexed_model(args.db)
    if model is None:
        raise ValueError("This index has no embeddings. Run 'offline-rag embed' first.")
    embedder = ollama_embedder(model, args.ollama_host, args.allow_remote)
    run = vector_search if args.mode == "vector" else hybrid_search
    return run(args.query, args.db, embedder, limit)


def _serve(args: argparse.Namespace) -> None:
    from .serve import make_server

    if not 0 <= args.port <= 65535:
        raise ValueError("--port must be between 0 and 65535")
    with make_server(args.db, args.port) as server:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        print(f"Serving {args.db} at {url} (read-only, this computer only). Press Ctrl+C to stop.")
        if args.open:
            import webbrowser

            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.db = resolve_db(args.db)
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
        elif args.command == "serve":
            _serve(args)
        elif args.command == "embed":
            embedder = ollama_embedder(args.model, args.ollama_host, args.allow_remote)
            count = embed_index(args.db, embedder, args.model, rebuild=args.rebuild)
            if args.json:
                _dump({"embedded": count, "model": args.model, "database": args.db})
            else:
                print(f"Embedded {count} passages with {args.model} in {args.db}")
        elif args.command == "search" and args.files:
            if args.mode != "lexical":
                raise ValueError("--files lists files that contain the words, so it only works with --mode lexical.")
            limit = args.limit if args.limit is not None else 20
            result = search_files(args.query, args.db, limit)
            if args.json:
                _dump({"query": args.query, **result})
            else:
                _print_files(args.query, result)
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
