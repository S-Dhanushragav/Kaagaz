"""Warm up the deployed backend 5 minutes before a demo, and time the sample path end to end.

    python scripts/warmup.py https://<workspace>--kaagaz-web.modal.run [--language mr] [--runs 1]

1. waits for /health (container started, sample video present, TTS models loaded),
2. runs the sample family: progress per stage, the question's audio, an answer by button, the plan, and the
   first plan sentence's audio; prints each time and the time to the first spoken sentence.
Standard library only.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def call(base: str, method: str, path: str, body: dict | None = None, timeout: float = 300) -> object:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if r.headers.get("content-type", "").startswith("application/json") else raw


def wait_healthy(base: str, limit_s: float = 600) -> dict:
    start = time.perf_counter()
    while True:
        try:
            health = call(base, "GET", "/health", timeout=120)
            if health.get("sample") and health.get("tts_models_loaded") in (3, None):
                print(f"[{time.perf_counter() - start:6.1f} s] healthy: {health}")
                return health
            print(f"[{time.perf_counter() - start:6.1f} s] starting: {health}")
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[{time.perf_counter() - start:6.1f} s] not up yet: {e}")
        if time.perf_counter() - start > limit_s:
            raise SystemExit("backend did not become healthy")
        time.sleep(5)


def run_sample(base: str, language: str) -> dict:
    t0 = time.perf_counter()
    now = lambda: round(time.perf_counter() - t0, 1)  # noqa: E731
    sid = call(base, "POST", "/sessions/sample", {"language": language})["id"]
    report: dict = {"session": sid, "stages": {}, "first_audio_s": None}
    seen = set()
    while True:
        v = call(base, "GET", f"/sessions/{sid}")
        for s in v["stages"]:
            if s["done"] and s["stage"] not in seen:
                seen.add(s["stage"])
                report["stages"][s["stage"]] = {"done_at_s": now(), "took_s": s["seconds"]}
                print(f"[{now():6.1f} s] {s['stage']} done ({s['seconds']} s)")
        if v["status"] == "error":
            raise SystemExit(f"session failed: {v['error']}")
        if v["status"] == "waiting":
            q = v["question"]
            audio = call(base, "GET", f"/sessions/{sid}/audio/question")
            if report["first_audio_s"] is None:
                report["first_audio_s"] = now()
            print(f"[{now():6.1f} s] question spoken ({len(audio)} bytes): {q['speech'][:90]}…")
            call(base, "POST", f"/sessions/{sid}/answer", {"question_id": q["question_id"], "option": 0})
            continue
        if v["status"] == "done":
            audio = call(base, "GET", f"/sessions/{sid}/audio/step-0") if v["speech"] else b""
            if report["first_audio_s"] is None and audio:
                report["first_audio_s"] = now()
            report["plan_s"] = now()
            report["steps"] = len(v["plan"]["steps"]) if v["plan"] else 0
            print(f"[{now():6.1f} s] plan ready: {report['steps']} steps; first plan sentence {len(audio)} bytes")
            break
        time.sleep(0.5)
    print(f"First spoken sentence after {report['first_audio_s']} s; plan after {report['plan_s']} s")
    return report


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url")
    parser.add_argument("--language", default="mr", choices=["mr", "hi", "en"])
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    wait_healthy(base)
    reports = [run_sample(base, args.language) for _ in range(args.runs)]
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
