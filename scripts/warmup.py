"""Warm up the deployed backend 5 minutes before a demo, and time the sample path end to end.

    python scripts/warmup.py https://<workspace>--kaagaz-web.modal.run [--language mr] [--runs 1]
    python scripts/warmup.py <URL> --language mr hi en ta te kn      # after a deploy: every language's plan cached
    python scripts/warmup.py <URL> --source video                     # the HH009 sweep video (testing)

1. waits for /health (container started, the sample family's photos present, six TTS models loaded),
2. runs the sample family (EV012's photos through photo mode): progress per stage, the question's audio, an answer
   by button, the plan, the first plan sentence's audio, and the close-up loop (the bundled clear photo of the
   document on the close-up list, then the re-plan); prints each time and the time to the first spoken sentence.
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
            if health.get("sample") and (health.get("tts_models_loaded") is None or health["tts_models_loaded"] >= 6):
                print(f"[{time.perf_counter() - start:6.1f} s] healthy: {health}")
                return health
            print(f"[{time.perf_counter() - start:6.1f} s] starting: {health}")
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[{time.perf_counter() - start:6.1f} s] not up yet: {e}")
        if time.perf_counter() - start > limit_s:
            raise SystemExit("backend did not become healthy")
        time.sleep(5)


def closeup(base: str, sid: str, document_id: str) -> dict:
    """The sample family's bundled close-up of one document (multipart form, as the app sends it)."""
    boundary = "kaagazwarmup"
    body = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                   for k, v in (("document_id", document_id), ("sample", "true"))) + f"--{boundary}--\r\n"
    req = urllib.request.Request(base + f"/sessions/{sid}/closeup", data=body.encode(), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def run_sample(base: str, language: str, source: str = "photos") -> dict:
    t0 = time.perf_counter()
    now = lambda: round(time.perf_counter() - t0, 1)  # noqa: E731
    sid = call(base, "POST", "/sessions/sample", {"language": language, "source": source})["id"]
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
            for doc in (v.get("recapture") or {}).get("documents") or []:
                t1 = time.perf_counter()
                result = closeup(base, sid, doc)
                while call(base, "GET", f"/sessions/{sid}")["status"] == "running":
                    time.sleep(0.5)
                report.setdefault("closeups", []).append({"document": doc, "clear": result.get("clear"),
                                                          "replan_s": round(time.perf_counter() - t1, 1)})
                print(f"[{now():6.1f} s] close-up {doc}: clear {result.get('clear')}, re-planned in "
                      f"{time.perf_counter() - t1:.1f} s")
            break
        time.sleep(0.5)
    print(f"First spoken sentence after {report['first_audio_s']} s; plan after {report['plan_s']} s")
    return report


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url")
    parser.add_argument("--language", nargs="+", default=["mr"], choices=["mr", "hi", "en", "ta", "te", "kn"])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--source", default="photos", choices=["photos", "video"])
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    wait_healthy(base)
    reports = [run_sample(base, language, args.source) for language in args.language for _ in range(args.runs)]
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
