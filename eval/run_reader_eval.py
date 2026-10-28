"""Evaluate the document reader on every photo-like synthetic document.

Usage (from the repo root, with the backend venv):
    python eval/run_reader_eval.py --model muse-spark-1.3
    python eval/run_reader_eval.py --model muse-spark-1.1 --dry-run

Reasoning effort is fixed at "low". Scores each extraction against ground_truth.json:
classification accuracy, and per document type the fields that are correct, wrong (a value
that differs from the document) and null (missing). Identity numbers are compared masked.
Summary -> eval/results/reader_<model>_<timestamp>.json; per-document details -> eval/results/raw/.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from graph.nodes.read_documents import MAX_PARALLEL, DocumentInput, ReadResult, read_documents  # noqa: E402
from synthetic.scoring import FieldScore, score_fields  # noqa: E402
from vision.images import encode_for_llm, read_image  # noqa: E402
from vision.text import mask_identity_number  # noqa: E402

HOUSEHOLDS = ROOT / "synthetic" / "households"
RESULTS = ROOT / "eval" / "results"
EFFORT = "low"


def expected_fields(doc: dict[str, Any]) -> dict[str, Any]:
    """Ground-truth fields as the reader should return them (identity numbers masked)."""
    fields = dict(doc["fields"])
    if "id_number" in fields:
        fields["id_number"] = mask_identity_number(fields["id_number"])
    return fields


def load_documents() -> list[tuple[str, dict[str, Any]]]:
    docs = []
    for path in sorted(HOUSEHOLDS.glob("HH*/ground_truth.json")):
        gt = json.loads(path.read_text(encoding="utf-8"))
        docs += [(path.parent.name, d) for d in gt["documents"]]
    return docs


def _pct(n: int, total: int) -> str:
    return f"{n} ({100 * n / total:.1f}%)" if total else "-"


def summarize(model: str, docs: list[tuple[str, dict[str, Any]]], results: list[ReadResult]) -> dict[str, Any]:
    per_type: dict[str, FieldScore] = defaultdict(FieldScore)
    overall = FieldScore()
    details = []
    classified = 0
    for (hh_id, doc), r in zip(docs, results):
        ex = r.extraction
        ok_type = ex.doc_type == doc["type"]
        classified += ok_type
        predicted = ex.fields.model_dump() if (ok_type and ex.fields is not None) else None
        s = score_fields(expected_fields(doc), predicted)
        per_type[doc["type"]].add(s)
        overall.add(s)
        details.append({
            "document": f"{hh_id}/{doc['id']}",
            "expected_type": doc["type"],
            "predicted_type": ex.doc_type,
            "unreadable": ex.unreadable,
            "error": ex.error,
            "correct": s.correct,
            "wrong": [{"field": p, "expected": e, "got": g} for p, e, g in s.wrong],
            "null": [{"field": p, "expected": e} for p, e in s.null],
            "attempts": r.attempts,
            "elapsed_s": round(r.elapsed_s, 2),
            "cached": r.cached,
            "usage": r.usage.model_dump(),
            "photo": doc.get("photo", {}),
        })

    fresh = [r.elapsed_s for r in results if not r.cached]
    return {
        "model": model,
        "reasoning_effort": EFFORT,
        "documents": len(docs),
        "classification": {"correct": classified, "total": len(docs)},
        "fields": {
            t: {"correct": s.correct, "wrong": len(s.wrong), "null": len(s.null), "total": s.total}
            for t, s in sorted(per_type.items())
        }
        | {"all": {"correct": overall.correct, "wrong": len(overall.wrong), "null": len(overall.null), "total": overall.total}},
        "unreadable_documents": sum(r.extraction.unreadable for r in results),
        "retried_documents": sum(r.attempts > 1 for r in results),
        "time_s": {
            "avg": round(sum(fresh) / len(fresh), 2) if fresh else None,
            "worst": round(max(fresh), 2) if fresh else None,
            "fresh_calls": len(fresh),
            "parallel": MAX_PARALLEL,
        },
        "tokens": {
            "avg_completion": round(sum(r.usage.completion_tokens for r in results) / len(results)),
            "total_prompt": sum(r.usage.prompt_tokens for r in results),
            "total_completion": sum(r.usage.completion_tokens for r in results),
        },
        "details": details,
    }


def print_summary(s: dict[str, Any]) -> None:
    c = s["classification"]
    print(f"\n# Reader eval: {s['model']} (effort {s['reasoning_effort']}), {s['documents']} documents")
    print(f"Classification: {c['correct']}/{c['total']}")
    print(f"Unreadable documents: {s['unreadable_documents']}   Retried: {s['retried_documents']}")
    print("\n| Document type | Correct | Wrong value | Null | Fields |")
    print("|---|---|---|---|---|")
    for t, f in s["fields"].items():
        print(f"| {t} | {_pct(f['correct'], f['total'])} | {_pct(f['wrong'], f['total'])} | {_pct(f['null'], f['total'])} | {f['total']} |")
    t, k = s["time_s"], s["tokens"]
    print(f"\nTime per document: avg {t['avg']} s, worst {t['worst']} s ({t['fresh_calls']} uncached, {t['parallel']} in parallel)")
    print(f"Tokens: avg completion {k['avg_completion']}, total prompt {k['total_prompt']}, total completion {k['total_completion']}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="Meta vision model ID, e.g. muse-spark-1.3")
    parser.add_argument("--dry-run", action="store_true", help="list documents; no API calls")
    args = parser.parse_args()

    docs = load_documents()
    if args.dry_run:
        print(f"{len(docs)} documents, 1 call each (+1 per retry), {MAX_PARALLEL} in parallel, model {args.model}, effort {EFFORT}")
        return

    inputs = [
        DocumentInput(
            id=f"{hh_id}/{doc['id']}",
            images=[encode_for_llm(read_image(HOUSEHOLDS / hh_id / doc["files"]["photo"]))],
        )
        for hh_id, doc in docs
    ]
    overrides = {"provider": "meta", "model": args.model, "reasoning_effort": EFFORT}
    results = read_documents(inputs, overrides=overrides)
    summary = summarize(args.model, docs, results)
    print_summary(summary)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    details = summary.pop("details")
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"reader_{args.model}_{stamp}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "raw" / f"reader_{args.model}_{stamp}.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nSaved {out.relative_to(ROOT)} (details in eval/results/raw/)")


if __name__ == "__main__":
    main()
