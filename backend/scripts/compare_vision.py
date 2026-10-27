"""Vision comparison on photo-like synthetic documents, scored against ground_truth.json.

Usage (from backend/):
    python scripts/compare_vision.py                      # 2x2 (model x effort) on the largest ration card
    python scripts/compare_vision.py --household HH008 --doc ration_card
    python scripts/compare_vision.py --all                # low-effort cells on every photo-like document
    python scripts/compare_vision.py --all --dry-run      # list what would be sent; no API calls

Each cell uses resolve() overrides, so cells never share a cached reply.
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND.parent)]

from clients.llm import LLMError, complete  # noqa: E402
from synthetic.scoring import score  # noqa: E402
from vision.images import encode_for_llm, read_image  # noqa: E402

HOUSEHOLDS = BACKEND.parent / "synthetic" / "households"
PROMPT = (BACKEND / "prompts" / "smoke_extract.md").read_text(encoding="utf-8")
CELLS_2X2 = [
    ("muse-spark-1.3", None),
    ("muse-spark-1.3", "low"),
    ("muse-spark-1.1", None),
    ("muse-spark-1.1", "low"),
]
CELLS_ALL = [("muse-spark-1.3", "low"), ("muse-spark-1.1", "low")]
MAX_PARALLEL = 4


@dataclass
class Result:
    hh_id: str
    doc: dict[str, Any]
    model: str
    effort: str | None
    correct: int = 0
    total: int = 0
    wrong: list[tuple[str, Any, Any]] = field(default_factory=list)
    completion_tokens: int = 0
    elapsed: float = 0.0
    cached: bool = False
    error: str | None = None


def skeleton(value: Any) -> Any:
    """Same shape as the ground-truth fields, values blanked; lists show one example row."""
    if isinstance(value, dict):
        return {k: skeleton(v) for k, v in value.items()}
    if isinstance(value, list):
        return [skeleton(value[0])] if value else []
    return ""


def parse_json(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def load_households() -> dict[str, dict[str, Any]]:
    return {
        p.parent.name: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(HOUSEHOLDS.glob("HH*/ground_truth.json"))
    }


def default_household(households: dict[str, dict[str, Any]]) -> str:
    def rows(gt: dict[str, Any]) -> int:
        card = next(d for d in gt["documents"] if d["type"] == "ration_card")
        return len(card["fields"]["members"])

    return max(households, key=lambda hh: (rows(households[hh]), [-ord(c) for c in hh]))


def run_cell(hh_id: str, doc: dict[str, Any], model: str, effort: str | None, max_tokens: int) -> Result:
    result = Result(hh_id, doc, model, effort)
    image = encode_for_llm(read_image(HOUSEHOLDS / hh_id / doc["files"]["photo"]))
    prompt = PROMPT.replace("{schema}", json.dumps(skeleton(doc["fields"]), ensure_ascii=False, indent=2))
    overrides = {"provider": "meta", "model": model, "reasoning_effort": effort}
    start = time.perf_counter()
    try:
        resp = complete(prompt, task="vision", image=image, max_tokens=max_tokens, overrides=overrides)
    except LLMError as e:
        result.error = str(e)
        result.elapsed = time.perf_counter() - start
        return result
    result.elapsed = time.perf_counter() - start
    result.cached = resp.cached
    result.completion_tokens = resp.usage.completion_tokens
    predicted = parse_json(resp.text)
    if predicted is None:
        result.error = "reply was not JSON"
    result.correct, result.total, result.wrong = score(doc["fields"], predicted or {})
    return result


def run_all(jobs: list[tuple[str, dict[str, Any], str, str | None]], max_tokens: int) -> list[Result]:
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        futures = [pool.submit(run_cell, *job, max_tokens) for job in jobs]
        return [f.result() for f in futures]


def _pct(correct: int, total: int) -> str:
    return f"{correct}/{total} ({100 * correct / total:.0f}%)" if total else "-"


def _effort(effort: str | None) -> str:
    return effort or "default"


def report_2x2(results: list[Result]) -> None:
    print("| Model | Effort | Accuracy | Completion tokens | Time (s) |")
    print("|---|---|---|---|---|")
    for r in results:
        if r.error and not r.total:
            print(f"| {r.model} | {_effort(r.effort)} | ERROR | - | {r.elapsed:.1f} |")
            continue
        t = "cached" if r.cached else f"{r.elapsed:.1f}"
        print(f"| {r.model} | {_effort(r.effort)} | {_pct(r.correct, r.total)} | {r.completion_tokens} | {t} |")
    for r in results:
        print(f"\n## {r.model} / {_effort(r.effort)}")
        if r.error:
            print(f"  {r.error}")
        for path, expected, got in r.wrong:
            print(f"  {path}: expected {expected!r}, got {got!r}")
        if r.total and not r.wrong:
            print("  all fields correct")


def report_all(results: list[Result]) -> None:
    by_model: dict[str, list[Result]] = defaultdict(list)
    for r in results:
        by_model[f"{r.model} / {_effort(r.effort)}"].append(r)
    doc_types = sorted({r.doc["type"] for r in results})

    print("| Model | Overall | " + " | ".join(doc_types) + " | Avg time (s) | Avg completion tokens | Errors |")
    print("|---|---|" + "---|" * len(doc_types) + "---|---|---|")
    for name, rs in by_model.items():
        overall = _pct(sum(r.correct for r in rs), sum(r.total for r in rs))
        per_type = [
            _pct(sum(r.correct for r in rs if r.doc["type"] == t), sum(r.total for r in rs if r.doc["type"] == t))
            for t in doc_types
        ]
        fresh = [r.elapsed for r in rs if not r.cached and not r.error]
        avg_time = f"{sum(fresh) / len(fresh):.1f}" if fresh else "cached"
        ok = [r for r in rs if not r.error]
        avg_tokens = f"{sum(r.completion_tokens for r in ok) / len(ok):.0f}" if ok else "-"
        errors = sum(1 for r in rs if r.error)
        print(f"| {name} | {overall} | " + " | ".join(per_type) + f" | {avg_time} | {avg_tokens} | {errors} |")

    for name, rs in by_model.items():
        print(f"\n## {name}: wrong fields")
        for r in rs:
            if r.error:
                print(f"  {r.hh_id}/{r.doc['id']}: {r.error}")
            for path, expected, got in r.wrong:
                print(f"  {r.hh_id}/{r.doc['id']} {path}: expected {expected!r}, got {got!r}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--household")
    parser.add_argument("--doc", default="ration_card")
    parser.add_argument("--all", action="store_true", help="low-effort cells on every photo-like document")
    parser.add_argument("--dry-run", action="store_true", help="list the calls that would be made; no API calls")
    parser.add_argument("--max-tokens", type=int, default=8000)
    args = parser.parse_args()

    households = load_households()
    if args.all:
        jobs = [
            (hh_id, doc, model, effort)
            for hh_id, gt in households.items()
            for doc in gt["documents"]
            for model, effort in CELLS_ALL
        ]
    else:
        hh_id = args.household or default_household(households)
        doc = next(d for d in households[hh_id]["documents"] if d["id"] == args.doc)
        print(f"Document: {hh_id}/{doc['files']['photo']}  photo: {doc['photo']}\n")
        jobs = [(hh_id, doc, model, effort) for model, effort in CELLS_2X2]

    if args.dry_run:
        docs = {(hh, d["id"]) for hh, d, _, _ in jobs}
        print(f"{len(jobs)} calls over {len(docs)} documents, at most {MAX_PARALLEL} in parallel:")
        for hh_id, doc, model, effort in jobs:
            print(f"  {hh_id}/{doc['files']['photo']}  {model} / {_effort(effort)}")
        return

    results = run_all(jobs, args.max_tokens)
    (report_all if args.all else report_2x2)(results)


if __name__ == "__main__":
    main()
