"""Load test: simultaneous sample checks and Ask questions against a local or staging backend (never production
during judging).

    python scripts/load_test.py http://localhost:8000 --checks 1 3 5 10 --asks 10 [--language mr]

For each level N, N sample checks start at the same moment (POST /sessions/sample); each answers the family question
with option 1 and runs to the plan. Reported per level: time to the first document, to the question, to the plan
(min / median / max), the highest place in line seen (the busy queue), and errors. Then N Ask questions at once about
one finished sample check: time to answer and the answer kinds. The sample's model calls are disk-cached on a warm
server, so a level measures the server itself (CPU: SAM mask decoding, cropping, rules, TTS), not the model APIs; Ask
questions are distinct, so they do call Muse Spark Open. Standard library only; results go to eval/results/.
"""

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from warmup import call  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = {  # distinct questions (distinct model calls), about the sample family's check and the five schemes
    "en": ["Why can't Lata apply for Ladki Bahin?", "Which documents does Omkar need for Shravanbal?",
           "What is Sanjay Gandhi Niradhar Yojana?", "Is Dattatray eligible for Ramai Awas?",
           "What should we fix first?", "Where do we correct a date of birth?", "Who in the family can get a pension?",
           "Does Lata need a new Aadhaar card?", "What is the income limit for Shravanbal?",
           "Why should Omkar check Ramai Awas at the office?"],
    "mr": ["लता लाडकी बहीण योजनेसाठी अर्ज का करू शकत नाही?", "श्रावणबाळ योजनेसाठी ओंकार यांना कोणती कागदपत्रे लागतील?",
           "संजय गांधी निराधार योजना काय आहे?", "दत्तात्रय रमाई आवास योजनेसाठी पात्र आहेत का?", "आधी काय दुरुस्त करावे?",
           "जन्मतारीख कुठे दुरुस्त करायची?", "कुटुंबात कोणाला पेन्शन मिळू शकते?", "लता यांना नवीन आधार कार्ड लागेल का?",
           "श्रावणबाळ योजनेसाठी उत्पन्नाची मर्यादा किती आहे?", "ओंकार यांनी रमाई आवासबद्दल कार्यालयात का विचारावे?"],
}


def stats(xs: list[float]) -> dict[str, float | None]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"min": None, "median": None, "max": None}
    return {"min": round(min(xs), 1), "median": round(statistics.median(xs), 1), "max": round(max(xs), 1)}


def one_check(base: str, language: str, start: threading.Event, out: dict) -> None:
    start.wait()
    t0 = time.perf_counter()
    now = lambda: round(time.perf_counter() - t0, 1)  # noqa: E731
    try:
        sid = call(base, "POST", "/sessions/sample", {"language": language})["id"]
        out["session"], out["max_queue_position"] = sid, 0
        while True:
            v = call(base, "GET", f"/sessions/{sid}")
            out["max_queue_position"] = max(out["max_queue_position"], v.get("queue_position") or 0)
            if out.get("first_document_s") is None and v.get("documents"):
                out["first_document_s"] = now()
            if v["status"] == "error":
                raise RuntimeError(v["error"])
            if v["status"] == "waiting":
                out.setdefault("question_s", now())
                call(base, "POST", f"/sessions/{sid}/answer", {"question_id": v["question"]["question_id"], "option": 0})
            elif v["status"] == "done":
                if v.get("speech"):
                    call(base, "GET", f"/sessions/{sid}/audio/step-0")
                out["plan_s"], out["steps"] = now(), len((v.get("plan") or {}).get("steps") or [])
                return
            time.sleep(0.5)
    except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError) as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["failed_at_s"] = now()


def check_level(base: str, n: int, language: str) -> dict:
    start, results = threading.Event(), [dict() for _ in range(n)]
    threads = [threading.Thread(target=one_check, args=(base, language, start, r)) for r in results]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join()
    errors = [r["error"] for r in results if "error" in r]
    return {"checks": n, "first_document_s": stats([r.get("first_document_s") for r in results]),
            "question_s": stats([r.get("question_s") for r in results]),
            "plan_s": stats([r.get("plan_s") for r in results]),
            "max_queue_position": max((r.get("max_queue_position") or 0) for r in results),
            "errors": errors, "sessions": [r.get("session") for r in results]}


def ask_level(base: str, n: int, language: str, session_id: str) -> dict:
    questions = (QUESTIONS.get(language) or QUESTIONS["en"]) * (n // 10 + 1)
    start, results = threading.Event(), [dict() for _ in range(n)]

    def one(q: str, out: dict) -> None:
        start.wait()
        t0 = time.perf_counter()
        try:
            a = call(base, "POST", "/ask", {"question": q, "language": language, "session_id": session_id}, timeout=120)
            out.update(seconds=round(time.perf_counter() - t0, 1), kind=a["kind"])
        except (urllib.error.URLError, TimeoutError) as e:
            out.update(seconds=round(time.perf_counter() - t0, 1), error=f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=one, args=(q, r)) for q, r in zip(questions, results)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join()
    kinds: dict[str, int] = {}
    for r in results:
        if "kind" in r:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return {"asks": n, "answer_s": stats([r.get("seconds") for r in results]), "kinds": kinds,
            "errors": [r["error"] for r in results if "error" in r]}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base")
    parser.add_argument("--checks", type=int, nargs="*", default=[1, 3, 5, 10])
    parser.add_argument("--asks", type=int, default=10)
    parser.add_argument("--language", default="mr")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    health = call(base, "GET", "/health")
    print(f"health: load {health.get('load')}, tts models {health.get('tts_models_loaded')}")
    report = {"base": base, "language": args.language, "load": health.get("load"), "levels": [], "ask": None}
    last_session = None
    for n in args.checks:
        level = check_level(base, n, args.language)
        report["levels"].append(level)
        last_session = next((s for s in level["sessions"] if s), last_session)
        p = level["plan_s"]
        print(f"{n:>2} checks: plan {p['min']} / {p['median']} / {p['max']} s (min/median/max); question "
              f"{level['question_s']['median']} s; first document {level['first_document_s']['median']} s; "
              f"highest place in line {level['max_queue_position']}; errors {len(level['errors'])} {level['errors'][:2]}")
    if args.asks and last_session:
        report["ask"] = ask_level(base, args.asks, args.language, last_session)
        a = report["ask"]
        print(f"{args.asks:>2} Ask questions: {a['answer_s']['min']} / {a['answer_s']['median']} / {a['answer_s']['max']} s; "
              f"kinds {a['kinds']}; errors {len(a['errors'])} {a['errors'][:2]}")
    out = ROOT / "eval" / "results" / f"load_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"Saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
