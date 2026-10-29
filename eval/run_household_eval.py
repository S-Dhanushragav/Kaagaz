"""Issue detection on the evaluation set EV001-EV030, against the planted errors.

Usage (from the repo root, with the backend venv):
    python eval/run_household_eval.py --mode truth              # documents from ground truth: no reader calls
    python eval/run_household_eval.py --mode e2e --dry-run      # count calls and estimate cost
    python eval/run_household_eval.py --mode e2e                # reader on photo-like images (muse-spark-1.3, low)

Reports, per planted error type: caught / planted; false alarms (scored issue types that match no
planted error), each with the reading errors in its documents (field, expected vs read); other issues (unreadable, duplicates, info notes); name-adjudicator calls; and the
rules engine's outcomes. Results -> eval/results/household_<mode>_<timestamp>.json.
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from graph.nodes.build_household import build_household, llm_adjudicator  # noqa: E402
from graph.nodes.read_documents import DocumentInput, read_documents  # noqa: E402
from rules.engine import evaluate  # noqa: E402
from schemas.documents import DocumentExtraction  # noqa: E402
from synthetic.truth import extractions_from_truth, match_issues  # noqa: E402
from vision.images import encode_for_llm, read_image  # noqa: E402
from vision.text import comparison_key, mask_identity_number  # noqa: E402

EVAL = ROOT / "synthetic" / "eval_households"
RESULTS = ROOT / "eval" / "results"
ERROR_TYPES = ["name_mismatch", "dob_mismatch", "expired", "missing_document", "not_on_ration_card"]

# Prices from https://dev.meta.ai/docs/pricing-rate-limits (checked 2026-10-29); per-document token
# averages from the Phase 3 reader eval (muse-spark-1.3, effort low).
LLM_INPUT_PER_TOKEN, LLM_OUTPUT_PER_TOKEN = 1.25 / 1e6, 4.25 / 1e6
AVG_PROMPT_TOKENS, AVG_COMPLETION_TOKENS = 1431, 515


def load() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(EVAL.glob("EV*/ground_truth.json"))]


def read_all(gts: list[dict[str, Any]], model: str) -> tuple[dict[str, list], dict[str, Any]]:
    """Read every photo-like document (one image each, so no frame agreement)."""
    inputs, owner = [], {}
    for gt in gts:
        for d in gt["documents"]:
            doc_id = f"{gt['id']}/{d['id']}"
            inputs.append(DocumentInput(id=doc_id, images=[encode_for_llm(read_image(EVAL / gt["id"] / d["files"]["photo"]))]))
            owner[doc_id] = (gt["id"], d["id"])
    start = time.perf_counter()
    results = read_documents(inputs, overrides={"provider": "meta", "model": model, "reasoning_effort": "low"})
    elapsed = time.perf_counter() - start
    per_household: dict[str, list] = defaultdict(list)
    for doc_input, r in zip(inputs, results):
        hh_id, doc_id = owner[doc_input.id]
        per_household[hh_id].append(r.extraction.model_copy(update={"document_id": doc_id}))
    usage = {
        "documents": len(results),
        "prompt_tokens": sum(r.usage.prompt_tokens for r in results),
        "completion_tokens": sum(r.usage.completion_tokens for r in results),
        "unreadable": sum(r.extraction.unreadable for r in results),
        "misclassified": sum(r.extraction.doc_type != next(d["type"] for d in gts_by_id(gts)[owner[i.id][0]]["documents"]
                                                            if d["id"] == owner[i.id][1]) for i, r in zip(inputs, results)),
        "read_s": round(elapsed, 1),
    }
    return per_household, usage


def gts_by_id(gts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {gt["id"]: gt for gt in gts}


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        return {k: v for key, item in value.items() for k, v in _flatten(item, f"{prefix}.{key}" if prefix else key).items()}
    if isinstance(value, list):
        return {k: v for i, item in enumerate(value) for k, v in _flatten(item, f"{prefix}[{i}]").items()}
    return {prefix: value}


def _same(expected: Any, read: Any) -> bool:
    if isinstance(expected, str) and isinstance(read, str):
        return comparison_key(expected) == comparison_key(read)
    return expected == read


def misreads(gt: dict[str, Any], issue: Any, extractions: list[DocumentExtraction]) -> list[dict[str, Any]]:
    """Reading errors in the documents behind a false alarm: (document, field, expected, read).

    Looks at the issue's documents; for a missing document or someone not on the ration card, also at
    the ration card and every document of the type in question (a misread name can unlink a document).
    """
    truth = {d["id"]: d for d in gt["documents"]}
    read = {ex.document_id: ex for ex in extractions}
    doc_ids = list(issue.documents)
    if issue.type in ("missing_document", "not_on_ration_card"):
        kind = issue.evidence.get("document_type")
        doc_ids += [d["id"] for d in gt["documents"] if d["type"] == "ration_card" or d["type"] == kind]
    out = []
    for doc_id in dict.fromkeys(doc_ids):
        t, ex = truth.get(doc_id), read.get(doc_id)
        if t is None or ex is None:
            continue
        if ex.doc_type != t["type"]:
            out.append({"document": doc_id, "field": "doc_type", "expected": t["type"], "read": ex.doc_type})
            continue
        expected_fields = dict(t["fields"])
        if "id_number" in expected_fields:
            expected_fields["id_number"] = mask_identity_number(expected_fields["id_number"])
        expected = _flatten(expected_fields)
        got = _flatten(ex.fields.model_dump()) if ex.fields else {}
        for path in sorted(set(expected) | set(got)):
            if path in expected and not _same(expected[path], got.get(path)):
                out.append({"document": doc_id, "field": path, "expected": expected[path], "read": got.get(path)})
    return out


def run(mode: str, model: str) -> dict[str, Any]:
    gts = load()
    usage: dict[str, Any] = {}
    if mode == "e2e":
        extractions, usage = read_all(gts, model)
    else:
        extractions = {gt["id"]: extractions_from_truth(gt) for gt in gts}

    planted, caught = Counter(), Counter()
    false_alarms: Counter = Counter()
    alarm_causes: Counter = Counter()
    other: Counter = Counter()
    outcomes: Counter = Counter()
    adjudicator_calls = 0
    details = []
    for gt in gts:
        ref = date.fromisoformat(gt["reference_date"])
        hh = build_household(extractions[gt["id"]], ref, adjudicate=llm_adjudicator(ref))
        adjudicator_calls += hh.llm_calls
        m = match_issues(gt, hh.issues)
        for p in gt["planted_errors"]:
            planted[p["type"]] += 1
        for p, _ in m.caught:
            caught[p["type"]] += 1
        alarm_reads = [misreads(gt, i, extractions[gt["id"]]) for i in m.false_alarms]
        for i, reads in zip(m.false_alarms, alarm_reads):
            false_alarms[i.type] += 1
            alarm_causes["misread" if reads else "no misread"] += 1
        for i in m.other:
            other[f"{i.type} ({i.severity})"] += 1
        for r in evaluate(hh):
            outcomes[r.outcome] += 1
        details.append({
            "household": gt["id"],
            "missed": [{"type": p["type"], "documents": p["documents"], "member": p["member_id"]} for p in m.missed],
            "false_alarms": [{"type": i.type, "member": i.member_id, "documents": i.documents, "evidence": i.evidence,
                              "misreads": reads} for i, reads in zip(m.false_alarms, alarm_reads)],
            "other": [{"type": i.type, "severity": i.severity, "documents": i.documents} for i in m.other],
            "llm_links": [l.model_dump() for l in hh.links if l.method == "llm"],
        })

    cost = 0.0
    if usage:
        cost = usage["prompt_tokens"] * LLM_INPUT_PER_TOKEN + usage["completion_tokens"] * LLM_OUTPUT_PER_TOKEN
    return {
        "mode": mode,
        "model": model if mode == "e2e" else None,
        "households": len(gts),
        "planted": dict(planted),
        "caught": dict(caught),
        "catch_rate": round(sum(caught.values()) / sum(planted.values()), 3),
        "false_alarms": dict(false_alarms),
        "false_alarm_total": sum(false_alarms.values()),
        "false_alarm_causes": dict(alarm_causes),
        "other_issues": dict(other),
        "adjudicator_calls": adjudicator_calls,
        "scheme_outcomes": dict(outcomes),
        "reader": usage,
        "reader_cost_usd": round(cost, 3),
        "details": details,
    }


def print_summary(s: dict[str, Any]) -> None:
    print(f"\n# Household issue detection: {s['mode']}" + (f" ({s['model']}, effort low)" if s["model"] else ""))
    print("\n| Error type | Caught / planted |\n|---|---|")
    for t in ERROR_TYPES:
        print(f"| {t} | {s['caught'].get(t, 0)}/{s['planted'].get(t, 0)} |")
    print(f"| **all** | **{sum(s['caught'].values())}/{sum(s['planted'].values())}** ({100 * s['catch_rate']:.1f}%) |")
    print(f"\nFalse alarms: {s['false_alarm_total']} {s['false_alarms']}; causes {s['false_alarm_causes']}")
    print(f"Other issues (not scored): {s['other_issues']}")
    print(f"Name-adjudicator calls (text model): {s['adjudicator_calls']}")
    print(f"Scheme outcomes (members x schemes): {s['scheme_outcomes']}")
    if s["reader"]:
        r = s["reader"]
        print(f"Reader: {r['documents']} documents in {r['read_s']} s, unreadable {r['unreadable']}, "
              f"misclassified {r['misclassified']}, tokens {r['prompt_tokens']} + {r['completion_tokens']}, "
              f"cost ${s['reader_cost_usd']}")
    for d in s["details"]:
        for x in d["missed"]:
            print(f"  MISSED {d['household']} {x['type']} {x['documents']}")
        for x in d["false_alarms"]:
            print(f"  FALSE  {d['household']} {x['type']} {x['member']} {x['documents']}")
            for r in x["misreads"]:
                print(f"         misread {r['document']} {r['field']}: expected {r['expected']!r}, read {r['read']!r}")
            if not x["misreads"]:
                print("         no misread in these documents (builder logic)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["truth", "e2e"], required=True)
    parser.add_argument("--model", default="muse-spark-1.3")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        gts = load()
        n = sum(len(gt["documents"]) for gt in gts)
        reads = 0 if args.mode == "truth" else n
        est = reads * (AVG_PROMPT_TOKENS * LLM_INPUT_PER_TOKEN + AVG_COMPLETION_TOKENS * LLM_OUTPUT_PER_TOKEN)
        print(f"{len(gts)} households, {n} documents; reader calls: {reads} (+ retries), "
              f"estimated reader cost ${est:.2f}; plus a name-adjudicator call (Baseten) for each 70-90 name score")
        return

    summary = run(args.mode, args.model)
    print_summary(summary)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"household_{args.mode}_{stamp}"
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    (RESULTS / "raw" / f"{name}.json").write_text(json.dumps(summary["details"], ensure_ascii=False, indent=2, default=str),
                                                  encoding="utf-8")
    (RESULTS / f"{name}.json").write_text(json.dumps({k: v for k, v in summary.items() if k != "details"},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved eval/results/{name}.json (details in eval/results/raw/)")


if __name__ == "__main__":
    main()
