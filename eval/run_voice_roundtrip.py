"""Voice round trip: MMS-TTS speaks option prompts and answers; Muse Voice Transcribe hears the answers;
agents/answers.py maps them to options. Reports, per language and setting, how often the answer maps to the
right option (and how often non-answers are correctly rejected), and the time per clip.

Usage (from the repo root, with the backend venv and the `tts` extra):
    python eval/run_voice_roundtrip.py --dry-run
    python eval/run_voice_roundtrip.py

Settings: 'plain' (the TTS clip as is, with keyword biasing), 'padded' (0.5 s of silence before and after,
with keywords), 'padded_no_kw' (padded, no keywords). Prompts and answer clips are saved to
eval/results/raw/voice/ for listening. Results -> eval/results/voice_roundtrip_<timestamp>.json.
"""

import argparse
import io
import json
import shutil
import sys
import time
import wave
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from agents.answers import NOT_SURE, keywords, match_answer, options_prompt  # noqa: E402
from agents.fix_planner import planner_issues  # noqa: E402
from agents.speech import speech_text  # noqa: E402
from agents.voice import DEVANAGARI, load_voice, question_text  # noqa: E402
from clients.transcribe import transcribe  # noqa: E402
from clients.tts import synthesize  # noqa: E402
from graph.nodes.build_household import build_household  # noqa: E402
from synthetic.truth import extractions_from_truth  # noqa: E402

EVAL = ROOT / "synthetic" / "eval_households"
RESULTS = ROOT / "eval" / "results"
AUDIO = RESULTS / "raw" / "voice"
LANGUAGES = ("en", "hi", "mr")
PAD_S = 0.5

# (spoken answer, expected option index for 3 options [a, b, not sure]; None = must not match)
ANSWERS = {
    "en": [("First", 0), ("Second", 1), ("The second one", 1), ("Number one", 0), ("Two", 1), ("Third", 2),
           ("Not sure", 2), ("I don't know", 2), ("Sunil Ramesh Patil", None), ("The one on the ration card", None)],
    "hi": [("पहला", 0), ("दूसरा", 1), ("दूसरा वाला", 1), ("नंबर दो", 1), ("दो", 1), ("तीसरा", 2), ("पता नहीं", 2),
           ("मुझे नहीं पता", 2), ("सुनील रमेश पाटील", None), ("राशन कार्ड वाला", None)],
    "mr": [("पहिले", 0), ("दुसरे", 1), ("दुसरा", 1), ("नंबर दोन", 1), ("दोन", 1), ("तिसरे", 2), ("माहीत नाही", 2),
           ("मला माहीत नाही", 2), ("सुनील रमेश पाटील", None), ("रेशन कार्डवरचे", None)],
}
SETTINGS = {"plain": (0.0, True), "padded": (PAD_S, True), "padded_no_kw": (PAD_S, False)}


def pad(audio: bytes, seconds: float) -> bytes:
    if not seconds:
        return audio
    with wave.open(io.BytesIO(audio), "rb") as w:
        rate, frames = w.getframerate(), w.readframes(w.getnframes())
    silence = np.zeros(int(rate * seconds), dtype="<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(silence + frames + silence)
    return out.getvalue()


def _shown(value: str, language: str) -> str:
    parts = value.split(" / ")
    for p in parts:
        if bool(DEVANAGARI.search(p)) == (language != "en"):
            return p
    return parts[0]


def prompts() -> dict[str, list[str]]:
    """Option prompts for a real name question and a real date-of-birth question from the EV set."""
    picked = {}
    for path in sorted(EVAL.glob("EV*/ground_truth.json")):
        gt = json.loads(path.read_text(encoding="utf-8"))
        hh = build_household(extractions_from_truth(gt), date.fromisoformat(gt["reference_date"]))
        for issue in planner_issues(hh):
            if issue.type in ("name_mismatch", "dob_mismatch") and issue.type not in picked and len(set(issue.values.values())) > 1:
                picked[issue.type] = issue
        if len(picked) == 2:
            break
    out = defaultdict(list)
    for language in LANGUAGES:
        not_sure = load_voice(language).options[NOT_SURE]
        for issue in picked.values():
            values = sorted(set(issue.values.values()))
            question = question_text(issue, "which_is_correct", language)
            out[language].append(options_prompt(question, [_shown(v, language) for v in values] + [not_sure], language))
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    n_calls = sum(len(a) for a in ANSWERS.values()) * len(SETTINGS)
    if args.dry_run:
        print(f"TTS clips: {sum(len(a) for a in ANSWERS.values())} answers + 6 prompts (local, CPU); "
              f"transcribe calls: {n_calls} (about $0.18 per audio hour)")
        return

    AUDIO.mkdir(parents=True, exist_ok=True)
    report: dict = {"settings": {k: {"pad_s": p, "keywords": kw} for k, (p, kw) in SETTINGS.items()}, "languages": {}}
    for language in LANGUAGES:
        lang = {"prompts": [], "answers": [], "summary": {}}
        for i, prompt in enumerate(prompts()[language], 1):
            sp = synthesize(speech_text(prompt, language), language)
            shutil.copy(sp.path, AUDIO / f"{language}_prompt{i}.wav")
            lang["prompts"].append({"text": prompt, "audio_s": round(sp.seconds, 2), "tts_s": round(sp.synth_s, 2)})
            print(f"[{language}] prompt {i} ({sp.seconds:.1f} s audio, TTS {sp.synth_s:.1f} s): {prompt}")
        options = ["a", "b", NOT_SURE]
        kw = keywords(options, language)
        for n, (spoken, expected) in enumerate(ANSWERS[language], 1):
            sp = synthesize(speech_text(spoken, language), language)
            shutil.copy(sp.path, AUDIO / f"{language}_answer{n}.wav")
            row = {"spoken": spoken, "expected": expected, "audio_s": round(sp.seconds, 2), "tts_s": round(sp.synth_s, 2)}
            for name, (pad_s, use_kw) in SETTINGS.items():
                t = transcribe(pad(sp.path.read_bytes(), pad_s), language, kw if use_kw else None)
                m = match_answer(t.text, options, language)
                row[name] = {"heard": t.text, "option": m.option, "ok": m.option == expected, "asr_s": t.request_s}
            lang["answers"].append(row)
            print(f"[{language}] {spoken!r:28} -> " + " | ".join(
                f"{k}: {row[k]['heard']!r} {'OK' if row[k]['ok'] else 'X'}" for k in SETTINGS))
        for name in SETTINGS:
            pos = [r for r in lang["answers"] if r["expected"] is not None]
            neg = [r for r in lang["answers"] if r["expected"] is None]
            lang["summary"][name] = {
                "answers_mapped_right": f"{sum(r[name]['ok'] for r in pos)}/{len(pos)}",
                "non_answers_rejected": f"{sum(r[name]['ok'] for r in neg)}/{len(neg)}",
                "asr_s_per_clip": round(sum(r[name]["asr_s"] for r in lang["answers"]) / len(lang["answers"]), 2),
            }
        lang["tts_s_per_answer_clip"] = round(sum(r["tts_s"] for r in lang["answers"]) / len(lang["answers"]), 2)
        lang["audio_s_per_answer_clip"] = round(sum(r["audio_s"] for r in lang["answers"]) / len(lang["answers"]), 2)
        report["languages"][language] = lang

    print("\n| Language | Setting | Answers mapped right | Non-answers rejected | ASR s/clip |\n|---|---|---|---|---|")
    for language, lang in report["languages"].items():
        for name, s in lang["summary"].items():
            print(f"| {language} | {name} | {s['answers_mapped_right']} | {s['non_answers_rejected']} | {s['asr_s_per_clip']} |")
    for language, lang in report["languages"].items():
        print(f"{language}: TTS {lang['tts_s_per_answer_clip']} s per answer clip "
              f"({lang['audio_s_per_answer_clip']} s audio; 0 when cached)")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (RESULTS / f"voice_roundtrip_{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved eval/results/voice_roundtrip_{stamp}.json; audio in eval/results/raw/voice/")


if __name__ == "__main__":
    main()
