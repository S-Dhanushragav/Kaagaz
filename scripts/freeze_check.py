"""Freeze checklist: run before and after every deploy. Exit code 0 only if every check passes.

    python scripts/freeze_check.py --api https://<workspace>--kaagaz-web.us-east.modal.run --site https://<site>.netlify.app
    python scripts/freeze_check.py --api http://localhost:8000 --site http://localhost:4173 --local   # a local copy

1. /health: up, the sample family's photos present, six TTS models loaded, the secrets production needs set (only
   whether they are set; /health never shows a value), and the non-secret settings equal to .env.example.
2. Modal: the `kaagaz-secrets` secret exists (modal CLI; skipped with --local or without the CLI).
3. The sample family end to end in Marathi: question answered, plan with spoken steps, the matrix with all four
   outcomes (eligible, fix first, check at office, not eligible), and the close-up loop (bundled close-up -> re-plan).
4. One Ask question in Marathi about that check: an answer, in Devanagari.
5. One voice question: the fixture clip (eval/fixtures/voice, a synthetic MMS-TTS voice) -> Muse Voice Transcribe ->
   Ask with the voice ticket.
6. Login -> save -> delete: demo login with a made-up number, the sample check claimed and listed under /me/checks,
   Delete my data, and the token no longer works. (Writes one user to the case-file database and deletes it.)
7. The site: no "Powered by Netlify" badge or other Netlify-injected content, and no request to any domain except the
   site and the API (headless Chromium via Playwright records every request; without Playwright, the HTML and its
   scripts and styles are scanned instead).
Standard library only (Playwright optional).
"""

import argparse
import json
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
CLIP = ROOT / "eval" / "fixtures" / "voice" / "mr_missing_income_certificate.wav"
ASK_MR = "आधी काय दुरुस्त करावे?"
OUTCOMES = {"eligible_on_documents", "blocked_by_issues", "check_at_office", "not_eligible"}
NEEDED_SECRETS = ("meta_api_key", "baseten_api_key", "database_url", "phone_hash_key", "token_signing_key")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

results: list[tuple[str, bool | None, str]] = []


def report(name: str, ok: bool | None, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
    print(f"[{mark}] {name}" + (f": {detail}" if detail else ""), flush=True)


def request(base: str, method: str, path: str, body: dict | None = None, token: str | None = None,
            data: bytes | None = None, content_type: str | None = None, timeout: float = 300) -> tuple[int, object]:
    headers = {}
    if body is not None:
        data, content_type = json.dumps(body).encode(), "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            ctype = r.headers.get("content-type", "")
            return r.status, json.loads(raw) if ctype.startswith("application/json") and raw else raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]


def env_example() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#"):
            out[key.strip()] = value.strip()
    return out


def check_health(api: str, local: bool) -> None:
    start = time.perf_counter()
    while True:
        status, h = request(api, "GET", "/health", timeout=120)
        if status == 200 and isinstance(h, dict) and (h.get("tts_models_loaded") or 0) >= 6:
            break
        if time.perf_counter() - start > 600:
            report("health", False, f"not ready after 10 min: {status} {h}")
            return
        time.sleep(5)
    report("health", h.get("status") == "ok" and h.get("sample") is True,
           f"up after {time.perf_counter() - start:.0f} s; sample photos {h.get('sample')}; sample video "
           f"{h.get('sample_video')}; TTS models {h.get('tts_models_loaded')}; load {h.get('load')}")
    configured = h.get("configured") or {}
    needed = [k for k in NEEDED_SECRETS if not (local and k == "database_url")]
    missing = [k for k in needed if not configured.get(k)]
    report("secrets set", not missing, "missing: " + ", ".join(missing) if missing else ", ".join(needed))
    expected = env_example()
    settings = h.get("settings") or {}
    wrong = {k: (v, expected.get(k)) for k, v in settings.items() if k in expected and expected[k] and str(v) != expected[k]}
    report("settings match .env.example", bool(settings) and not wrong,
           f"differ (server, .env.example): {wrong}" if wrong else f"{len(settings)} settings checked")
    budget = h.get("baseten_budget") or {}
    report("Baseten budget", budget.get("remaining", 0) > 0,
           f"{budget.get('tokens')} of {budget.get('limit')} tokens used today; refused {budget.get('refused')}")


def check_modal_secret(local: bool) -> None:
    if local:
        report("Modal secret kaagaz-secrets", None, "--local")
        return
    modal = shutil.which("modal")
    if not modal:
        report("Modal secret kaagaz-secrets", None, "modal CLI not found")
        return
    out = subprocess.run([modal, "secret", "list"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    report("Modal secret kaagaz-secrets", out.returncode == 0 and "kaagaz-secrets" in out.stdout,
           "listed" if "kaagaz-secrets" in out.stdout else (out.stderr or out.stdout)[-200:])


def wait(api: str, sid: str, limit_s: float = 300) -> dict:
    end = time.perf_counter() + limit_s
    while time.perf_counter() < end:
        status, v = request(api, "GET", f"/sessions/{sid}")
        if status != 200:
            raise RuntimeError(f"GET /sessions/{sid}: {status} {v}")
        if v["status"] != "running":
            return v
        time.sleep(0.5)
    raise RuntimeError("the check did not finish in time")


def check_sample(api: str) -> dict | None:
    t0 = time.perf_counter()
    status, started = request(api, "POST", "/sessions/sample", {"language": "mr"})
    if status != 200:
        report("sample check", False, f"POST /sessions/sample: {status} {started}")
        return None
    sid = started["id"]
    try:
        v = wait(api, sid)
        question_s = None
        while v["status"] == "waiting":
            question_s = question_s or round(time.perf_counter() - t0, 1)
            status, audio = request(api, "GET", f"/sessions/{sid}/audio/question")
            if status != 200 or not audio:
                raise RuntimeError(f"question audio: {status}")
            request(api, "POST", f"/sessions/{sid}/answer", {"question_id": v["question"]["question_id"], "option": 0})
            v = wait(api, sid)
        if v["status"] != "done":
            raise RuntimeError(f"status {v['status']}: {v.get('error')}")
        plan_s = round(time.perf_counter() - t0, 1)
        status, audio = request(api, "GET", f"/sessions/{sid}/audio/step-0")
        steps = len((v.get("plan") or {}).get("steps") or [])
        report("sample check", steps > 0 and status == 200 and bool(audio),
               f"question at {question_s} s, plan at {plan_s} s, {steps} steps, first step audio {len(audio or b'')} bytes")
        closeups = (v.get("recapture") or {}).get("documents") or []
        if closeups:
            t1 = time.perf_counter()
            ctype, form = multipart({"document_id": closeups[0], "sample": "true"})
            status, res = request(api, "POST", f"/sessions/{sid}/closeup", data=form, content_type=ctype)
            v = wait(api, sid)
            report("close-up loop", status == 200 and res.get("clear") is True and v["status"] == "done"
                   and not (v.get("recapture") or {}).get("documents"),
                   f"{closeups[0]} clear={res.get('clear') if isinstance(res, dict) else res}, re-planned in "
                   f"{time.perf_counter() - t1:.1f} s")
        else:
            report("close-up loop", False, "no document on the close-up list (the sample's blurred photo was read clearly)")
        seen = {r["outcome"] for r in v.get("results") or [] if not str(r["member_id"]).startswith("x")}
        report("matrix: four outcomes", OUTCOMES <= seen, f"seen {sorted(seen)}")
        return {"id": sid, "guest_secret": started["guest_secret"]}
    except RuntimeError as e:
        report("sample check", False, str(e))
        return None


def multipart(fields: dict[str, str], file: tuple[str, str, bytes] | None = None) -> tuple[str, bytes]:
    boundary = "kaagaz" + secrets.token_hex(8)
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    if file:
        name, filename, data = file
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


def check_ask(api: str, session: dict | None) -> None:
    body = {"question": ASK_MR, "language": "mr", "session_id": session["id"] if session else None}
    t0 = time.perf_counter()
    status, a = request(api, "POST", "/ask", body, timeout=60)
    ok = status == 200 and a.get("kind") == "answer" and bool(DEVANAGARI.search(a.get("text") or ""))
    report("Ask in Marathi", ok, f"{time.perf_counter() - t0:.1f} s, {a.get('kind') if isinstance(a, dict) else status}: "
           f"{(a.get('text') or '')[:80] if isinstance(a, dict) else a}")


def check_voice(api: str, session: dict | None) -> None:
    fields = {"language": "mr", **({"session_id": session["id"]} if session else {})}
    ctype, data = multipart(fields, ("audio", CLIP.name, CLIP.read_bytes()))
    t0 = time.perf_counter()
    status, heard = request(api, "POST", "/ask/transcribe", data=data, content_type=ctype, timeout=60)
    if status != 200 or not heard.get("text"):
        report("voice question", False, f"transcribe: {status} {heard}")
        return
    transcribe_s = time.perf_counter() - t0
    status, a = request(api, "POST", "/ask", {"question": heard["text"], "language": "mr", "voice_ticket": heard["voice_ticket"],
                                              "session_id": session["id"] if session else None}, timeout=60)
    report("voice question", status == 200 and a.get("kind") in ("answer", "not_sure"),
           f"heard '{heard['text']}' in {transcribe_s:.1f} s; Ask {a.get('kind') if isinstance(a, dict) else status}")


def check_account(api: str, session: dict | None) -> None:
    status, cfg = request(api, "GET", "/auth/config")
    if status != 200 or cfg.get("mode") != "demo":
        report("login -> save -> delete", None, f"auth mode {cfg}: needs a real phone")
        return
    phone = "9" + "".join(str(secrets.randbelow(10)) for _ in range(9))  # a made-up number
    status, started = request(api, "POST", "/auth/start", {"phone": phone})
    if status != 200 or not started.get("demo_code"):
        report("login -> save -> delete", False, f"auth/start: {status} {started}")
        return
    status, verified = request(api, "POST", "/auth/verify", {"phone": phone, "code": started["demo_code"], "language": "mr"})
    if status != 200:
        report("login -> save -> delete", False, f"auth/verify: {status} {verified}")
        return
    token = verified["token"]
    saved = None
    if session:
        status, claimed = request(api, "POST", f"/sessions/{session['id']}/claim", {"guest_secret": session["guest_secret"]},
                                  token=token)
        saved = claimed.get("check_id") if status == 200 else None
        status, checks = request(api, "GET", "/me/checks", token=token)
        listed = status == 200 and any(c.get("id") == saved for c in checks)
    else:
        listed = False
    status_delete, _ = request(api, "DELETE", "/me", token=token)
    status_after, _ = request(api, "GET", "/me", token=token)
    report("login -> save -> delete", bool(saved) and listed and status_delete == 204 and status_after == 401,
           f"saved check {saved}, listed {listed}, delete {status_delete}, /me afterwards {status_after}")


def check_site(site: str, api: str) -> None:
    allowed = {urlparse(site).netloc, urlparse(api).netloc}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sync_playwright = None
    if sync_playwright is not None:
        hosts: dict[str, int] = {}
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 360, "height": 780})
            page.on("request", lambda r: hosts.__setitem__(urlparse(r.url).netloc, hosts.get(urlparse(r.url).netloc, 0) + 1)
                    if urlparse(r.url).scheme in ("http", "https") else None)
            page.goto(site, wait_until="networkidle")
            for label in ("मराठी", "தமிழ்"):  # open a language with a lazy font too
                try:
                    page.get_by_text(label, exact=True).first.click(timeout=2000)
                    page.wait_for_load_state("networkidle")
                except Exception:  # noqa: BLE001 - the picker may be elsewhere; the page load is what matters
                    pass
            text = page.inner_text("body")
            html = page.content()
            browser.close()
        foreign = {h: n for h, n in hosts.items() if h not in allowed}
        report("third-party requests", not foreign, f"hosts {hosts}" + (f"; not allowed: {foreign}" if foreign else ""))
    else:
        status, raw = request(site, "GET", "/")
        html = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        text = html
        refs = re.findall(r'(?:src|href)="([^"]+)"', html)
        foreign = sorted({urlparse(urljoin(site, r)).netloc for r in refs} - allowed)
        report("third-party requests (static scan, no Playwright)", not foreign, f"not allowed: {foreign}" if foreign else
               f"{len(refs)} references, all on {sorted(allowed)}")
    badge = re.search(r"netlify", text, re.I) or re.search(r"netlify-(badge|drawer)|netlify\.com", html, re.I)
    report("no Netlify badge", badge is None, "found: " + badge.group(0) if badge else "none on the page")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", required=True)
    parser.add_argument("--site", help="the frontend's URL (skipped if not given)")
    parser.add_argument("--local", action="store_true", help="a local copy: no database or Modal secret needed")
    args = parser.parse_args()
    api = args.api.rstrip("/")
    print(f"Freeze check of {api}" + (f" and {args.site}" if args.site else "") + f" at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    check_health(api, args.local)
    check_modal_secret(args.local)
    session = check_sample(api)
    check_ask(api, session)
    check_voice(api, session)
    check_account(api, session)
    if args.site:
        check_site(args.site.rstrip("/"), api)
    else:
        report("site", None, "no --site given")
    failed = [n for n, ok, _ in results if ok is False]
    print(f"\n{sum(ok is True for _, ok, _ in results)} passed, {len(failed)} failed, "
          f"{sum(ok is None for _, ok, _ in results)} skipped" + (f": {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
