"""Retrieval evaluation: recall@k and MRR over a questions file.

Usage: python -m offline_rag.eval [--corpus eval/corpus] [--questions eval/questions.json] [--json]

A hit is relevant when it comes from the expected file and its passage contains
the expected text (case-insensitive).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .index import ingest, search

KS = (1, 3, 5)


def evaluate(corpus: Path, questions: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        database = Path(tmp) / "eval.sqlite3"
        ingest(corpus, database)
        rows = []
        for item in questions:
            hits = search(item["q"], database, limit=max(KS))
            rank = next(
                (
                    i
                    for i, hit in enumerate(hits, start=1)
                    if hit["path"] == item["path"] and item["contains"].lower() in hit["body"].lower()
                ),
                None,
            )
            rows.append({"q": item["q"], "kind": item.get("kind", "all"), "rank": rank})
    return {"rows": rows, **_summarize(rows)}


def _summarize(rows: list[dict]) -> dict:
    def stats(subset: list[dict]) -> dict:
        n = len(subset) or 1
        out = {"questions": len(subset)}
        for k in KS:
            out[f"recall@{k}"] = round(sum(1 for r in subset if r["rank"] and r["rank"] <= k) / n, 3)
        out["mrr"] = round(sum(1 / r["rank"] for r in subset if r["rank"]) / n, 3)
        return out

    kinds = sorted({r["kind"] for r in rows})
    return {"overall": stats(rows), "by_kind": {k: stats([r for r in rows if r["kind"] == k]) for k in kinds}}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m offline_rag.eval", description=__doc__)
    parser.add_argument("--corpus", default="eval/corpus", type=Path)
    parser.add_argument("--questions", default="eval/questions.json", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        questions = json.loads(args.questions.read_text(encoding="utf-8"))["questions"]
        report = evaluate(args.corpus, questions)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"{'subset':<12}{'n':>4}" + "".join(f"{'R@' + str(k):>8}" for k in KS) + f"{'MRR':>8}")
    for name, st in [("overall", report["overall"]), *report["by_kind"].items()]:
        print(f"{name:<12}{st['questions']:>4}" + "".join(f"{st[f'recall@{k}']:>8.3f}" for k in KS) + f"{st['mrr']:>8.3f}")
    missed = [r["q"] for r in report["rows"] if not r["rank"]]
    if missed:
        print("\nNot found in top 5:")
        for q in missed:
            print(f"  - {q}")


if __name__ == "__main__":
    main()
