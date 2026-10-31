"""Ask Kaagaz eval: 30 questions (eval/ask_questions.yaml) in en/hi/mr on the 5 schemes and the sample family.

Usage (from the repo root, with the backend venv):
    python eval/run_ask_eval.py            # offline: replays the recorded model replies (eval/fixtures/ask/llm.json)
    python eval/run_ask_eval.py --live     # calls Muse Spark Open on Baseten and records the replies (costs tokens)

Report: answered, answered correctly (every required fact), correctly refused, fact-check failures caught (replies
rejected by agents/ask_check.py before anything was shown), "not sure" fallbacks, and wrong answers shown (an answer
shown with a forbidden statement, or an answer where a refusal was expected). Tokens per answer.
Results -> eval/results/ask_<timestamp>.json (answers, failures and traces).
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from agents.ask import ask  # noqa: E402
from agents.ask_tools import FamilyContext  # noqa: E402
from clients.cache import make_key  # noqa: E402
from clients.llm import ChatResponse, EmptyResponse, LLMError, chat  # noqa: E402

QUESTIONS = ROOT / "eval" / "ask_questions.yaml"
FIXTURES = ROOT / "eval" / "fixtures" / "ask"
RECORDING = FIXTURES / "llm.json"
RESULTS = ROOT / "eval" / "results"
REFUSALS = ("out_of_scope", "id_number", "other_language", "not_sure")
EMPTY = {"empty": True}


class Replay:
    """Model replies by request: recorded on --live runs, replayed offline (a request never recorded is an error)."""

    def __init__(self, live: bool) -> None:
        self.live = live
        self.recorded: dict[str, Any] = json.loads(RECORDING.read_text(encoding="utf-8")) if RECORDING.exists() else {}
        self.new = 0
        self.used: set[str] = set()

    def __call__(self, messages, **kwargs) -> ChatResponse:
        key = make_key({"messages": list(messages), "tools": kwargs.get("tools"), "tool_choice": kwargs.get("tool_choice"),
                        "task": kwargs.get("task")})
        self.used.add(key)
        if not self.live:  # offline: only what a live run recorded
            if key not in self.recorded:
                raise LLMError("no recorded reply for this request: run with --live to record")
            if self.recorded[key] == EMPTY:
                raise EmptyResponse("recorded: the model returned nothing")
            return ChatResponse.model_validate(self.recorded[key])
        self.new += key not in self.recorded
        try:
            resp = chat(messages, **kwargs)  # live: always the model (through the disk cache), recorded afresh
        except EmptyResponse:
            self.recorded[key] = EMPTY  # not cached by the client, so recorded here
            raise
        self.recorded[key] = resp.model_dump(mode="json")
        return resp

    def save(self, prune: bool) -> None:
        """`prune` (a full run): keep only the replies this run used, so the fixture holds no stale prompts."""
        keep = {k: v for k, v in self.recorded.items() if k in self.used} if prune else self.recorded
        RECORDING.write_text(json.dumps(keep, ensure_ascii=False, indent=0), encoding="utf-8")


def grade(q: dict[str, Any], kind: str, text: str, chips: int) -> dict[str, Any]:
    low = text.casefold()
    forbidden = [f for f in q.get("forbid", []) if f.casefold() in low]
    if q.get("forbid_regex") and re.search(q["forbid_regex"], text):
        forbidden.append(q["forbid_regex"])
    required_ok = all(any(r.casefold() in low for r in group) for group in q.get("require", []))
    answered = kind == "answer"
    wrong = answered and (bool(forbidden) or q["expect"] == "refuse")
    return {"answered": answered, "correct": answered and required_ok and not wrong,
            "refused_ok": q["expect"] in ("refuse", "either") and kind in REFUSALS,
            "wrong_shown": wrong, "forbidden": forbidden, "required_ok": required_ok,
            "chips_ok": (chips > 0) if q.get("chips") else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="call the model and record its replies")
    parser.add_argument("--only", nargs="*", help="question ids")
    args = parser.parse_args()

    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]
    family = FamilyContext.model_validate_json((FIXTURES / "sample_family.json").read_text(encoding="utf-8"))
    llm = Replay(args.live)
    rows = []
    for q in questions:
        ctx = None
        if q["family"]:
            ctx = family.model_copy(deep=True)
            if q.get("inject"):
                ctx.data.members[1].relation_en = q["inject"]  # instructions inside a document field
        start = time.perf_counter()
        a = ask(q["q"], q["lang"], ctx, llm=llm, timeout_s=60 if args.live else 20)
        g = grade(q, a.kind, a.text, len(a.chips))
        rows.append({"id": q["id"], "lang": q["lang"], "question": q["q"], "expect": q["expect"], "kind": a.kind,
                     "text": a.text, "note": a.note, "sources": [s.url for s in a.sources],
                     "chips": [c.label for c in a.chips], "attempts": a.attempts, "tool_calls": a.tool_calls,
                     "check_failures": a.failures, "tokens": a.usage.model_dump(), "seconds": round(time.perf_counter() - start, 2),
                     **g, "trace": a.trace})
        mark = "WRONG" if g["wrong_shown"] else "ok" if g["correct"] or g["refused_ok"] else "--"
        print(f"{q['id']:4} {q['lang']} {a.kind:14} {mark:5} attempts={a.attempts} tools={a.tool_calls} "
              f"tokens={a.usage.total_tokens:5} {a.seconds:4.1f}s  {a.text[:90]!r}")
    if args.live:
        llm.save(prune=not args.only)

    n = len(rows)
    by_lang = {lang: sum(r["lang"] == lang for r in rows) for lang in ("en", "hi", "mr")}
    summary = {
        "questions": n, "by_language": by_lang,
        "answered": sum(r["answered"] for r in rows),
        "answered_correctly": sum(r["correct"] for r in rows),
        "expected_answers": sum(q["expect"] == "answer" for q in questions),
        "correctly_refused": sum(r["refused_ok"] for r in rows),
        "expected_refusals": sum(q["expect"] in ("refuse", "either") for q in questions),
        "not_sure": sum(r["kind"] == "not_sure" for r in rows),
        "unavailable": sum(r["kind"] == "unavailable" for r in rows),
        "fact_check_failures_caught": sum(bool(r["check_failures"]) for r in rows),
        "wrong_answers_shown": sum(r["wrong_shown"] for r in rows),
        "chips_offered_when_expected": f"{sum(bool(r['chips_ok']) for r in rows)}/{sum(r['chips_ok'] is not None for r in rows)}",
        "tokens": {"prompt": sum(r["tokens"]["prompt_tokens"] for r in rows),
                   "completion": sum(r["tokens"]["completion_tokens"] for r in rows)},
        "mean_tokens_per_question": round(sum(r["tokens"]["total_tokens"] for r in rows) / max(n, 1)),
        "mean_seconds": round(sum(r["seconds"] for r in rows) / max(n, 1), 2),
        "mode": "live" if args.live else "replay", "new_recordings": llm.new,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"ask_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
