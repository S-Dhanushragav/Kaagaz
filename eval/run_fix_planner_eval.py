"""Fix planner on 10 EV households with issues (households built end to end; reads are cached).

Usage (from the repo root, with the backend venv):
    python eval/run_fix_planner_eval.py --dry-run     # which households, how many issues
    python eval/run_fix_planner_eval.py               # run the agent (muse-spark-1.3)

A simulated family answers ask_family from the ground truth: 'compare' -> same/different by the true
values on the documents; 'which_is_correct' -> the option that is a member's true name or date of birth.
Reports: plans passing verification first time, retries, fallbacks, steps per plan, tokens and cost.
Results -> eval/results/fix_planner_<timestamp>.json (plans and traces in eval/results/raw/).
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from agents.fix_planner import plan_fixes, planner_issues  # noqa: E402
from agents.tools import NOT_SURE  # noqa: E402
from agents.voice import plan_voice  # noqa: E402
from eval.run_household_eval import LLM_INPUT_PER_TOKEN, LLM_OUTPUT_PER_TOKEN, load, read_all  # noqa: E402
from graph.nodes.build_household import build_household, llm_adjudicator, llm_name_verifier  # noqa: E402
from rules.engine import evaluate  # noqa: E402
from schemas.fixes import PlannerIssue  # noqa: E402
from vision.text import comparison_key  # noqa: E402

RESULTS = ROOT / "eval" / "results"
N_HOUSEHOLDS = 10


def _dob(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def simulated_family(gt: dict[str, Any]):
    """Answers from the ground truth, as a family looking at its own documents would."""
    truths = set()
    for m in gt["members"]:
        for s in ("mr", "en"):
            truths.add(comparison_key(f"{m['given'][s]} {m['middle'][s]} {m['surname'][s]}"))
        truths.add(comparison_key(_dob(m["dob"])))
    docs = {d["id"]: d for d in gt["documents"]}

    def true_values(issue: PlannerIssue) -> set[str]:
        out = set()
        for doc_id in issue.values:
            d = docs.get(doc_id)
            if d is None:
                continue
            f = d["fields"]
            if issue.type == "dob_mismatch":
                out.add(f.get("dob"))
            elif d["type"] == "ration_card":
                row = int((issue.member_id or "r0")[1:]) - 1
                rows = f["members"]
                if 0 <= row < len(rows):
                    out.add((rows[row]["name_mr"], rows[row]["name_en"]))
            else:
                out.add((f.get("name_mr"), f.get("name_en")))
        return out

    def answer(issue: PlannerIssue, kind: str, question: str, options: list[str]) -> str:
        if kind == "compare":
            want = "same" if len(true_values(issue)) <= 1 else "different"
            return next((o for o in options if want in o.lower()), NOT_SURE)
        for o in options:
            if any(comparison_key(p) in truths for p in [o, *o.split(" / ")]):
                return o
        return NOT_SURE

    return answer


def build(gts: list[dict[str, Any]], model: str):
    extractions, images, _ = read_all(gts, model)
    out = []
    for gt in gts:
        ref = date.fromisoformat(gt["reference_date"])
        verify = llm_name_verifier(images[gt["id"]], overrides={"provider": "meta", "model": model})
        hh = build_household(extractions[gt["id"]], ref, adjudicate=llm_adjudicator(ref), verify=verify)
        results = evaluate(hh)
        out.append((gt, hh, results, planner_issues(hh, results)))
    return out


def pick(built: list) -> list:
    """10 households with issues, covering as many (issue type, severity) pairs as possible."""
    with_issues = [b for b in built if b[3]]
    kinds = lambda b: {(i.type, i.severity) for i in b[3]}  # noqa: E731
    return sorted(with_issues, key=lambda b: (-len(kinds(b)), b[0]["id"]))[:N_HOUSEHOLDS]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="muse-spark-1.3")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chosen = pick(build(load(), args.model))
    issue_mix = Counter((i.type, i.severity) for b in chosen for i in b[3])
    print(f"Households: {[b[0]['id'] for b in chosen]}")
    print(f"Issues: {sum(len(b[3]) for b in chosen)} {dict(issue_mix)}")
    if args.dry_run:
        print("Agent calls: a few turns per household (task 'agent', cached after the first run)")
        return

    rows, plans = [], {}
    start_all = time.perf_counter()
    for gt, hh, results, issues in chosen:
        start = time.perf_counter()
        plan = plan_fixes(hh, results, simulated_family(gt), overrides={"provider": "meta", "model": args.model})
        kinds = Counter(s.kind for s in plan.steps)
        rows.append({"household": gt["id"], "issues": len(issues), "source": plan.source, "attempts": plan.attempts,
                     "turns": plan.turns, "steps": len(plan.steps), "questions": kinds["question"],
                     "fixes": kinds["fix"], "ask_at_office": kinds["ask_at_office"],
                     "visits": len({s.visit for s in plan.steps if s.visit}),
                     "first_errors": plan.verification_errors,
                     "tokens": [plan.usage.prompt_tokens, plan.usage.completion_tokens],
                     "seconds": round(time.perf_counter() - start, 1)})
        voices = {lang: plan_voice(plan.steps, issues, lang) for lang in ("en", "hi", "mr")}
        plans[gt["id"]] = {"issues": [i.model_dump() for i in issues], "plan": plan.model_dump(mode="json"), "voice": voices}
        r = rows[-1]
        print(f"\n## {gt['id']}: {r['source']} (attempts {r['attempts']}, turns {r['turns']}), {r['steps']} steps, "
              f"{r['visits']} visits, {r['seconds']} s")
        for e in r["first_errors"]:
            print(f"   rejected: {e}")
        for s in plan.steps:
            head = s.procedure_id or s.kind
            extra = f" -> {s.answer}" if s.kind == "question" else f" @ {s.office}" if s.office else ""
            print(f"   [{s.kind}{'' if s.visit is None else f' visit {s.visit}'}] {head} {s.issue_ids}{extra}: {s.voice}")

    prompt = sum(r["tokens"][0] for r in rows)
    completion = sum(r["tokens"][1] for r in rows)
    sources = Counter(r["source"] for r in rows)
    summary = {
        "model": args.model, "households": [r["household"] for r in rows], "issue_mix": {f"{t} ({s})": n for (t, s), n in issue_mix.items()},
        "first_time_pass": sources["agent"], "passed_after_retry": sources["agent_retry"], "fallbacks": sources["fallback"],
        "steps_per_plan": round(sum(r["steps"] for r in rows) / len(rows), 1),
        "fix_steps_per_plan": round(sum(r["fixes"] for r in rows) / len(rows), 1),
        "ask_at_office_steps": sum(r["ask_at_office"] for r in rows),
        "turns_per_plan": round(sum(r["turns"] for r in rows) / len(rows), 1),
        "tokens": [prompt, completion],
        "cost_usd": round(prompt * LLM_INPUT_PER_TOKEN + completion * LLM_OUTPUT_PER_TOKEN, 3),
        "seconds": round(time.perf_counter() - start_all, 1),
        "per_household": rows,
    }
    print(f"\n# Fix planner ({args.model}), {len(rows)} households")
    print(f"First-time pass {summary['first_time_pass']}/{len(rows)}, after retry {summary['passed_after_retry']}, "
          f"fallbacks {summary['fallbacks']}")
    print(f"Steps per plan {summary['steps_per_plan']} (fixes {summary['fix_steps_per_plan']}), ask-at-office steps "
          f"{summary['ask_at_office_steps']}, turns per plan {summary['turns_per_plan']}")
    print(f"Tokens {prompt} + {completion}, cost ${summary['cost_usd']}, {summary['seconds']} s")
    for hh_id in list(plans)[:3]:
        print(f"\n## Sentences, {hh_id}")
        for lang in ("en", "hi", "mr"):
            for sentence in plans[hh_id]["voice"][lang]:
                print(f"   [{lang}] {sentence}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    (RESULTS / "raw" / f"fix_planner_{stamp}.json").write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / f"fix_planner_{stamp}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved eval/results/fix_planner_{stamp}.json (plans and traces in eval/results/raw/)")


if __name__ == "__main__":
    main()
