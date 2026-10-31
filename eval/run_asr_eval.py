"""Spoken questions: recognition (Muse Voice Transcribe) and whether the transcript still gets the right answer.

Usage (from the repo root, with the backend venv):
    python eval/run_asr_eval.py --clips <folder>        # your recordings (see below)
    python eval/run_asr_eval.py --synthetic             # MMS-TTS clips of 12 questions (a weak proxy for real voices)
    add --no-answers to skip asking Kaagaz (recognition only; no Baseten tokens)

A clips folder holds audio files (.wav .webm .m4a .mp4 .ogg .mp3) and either `clips.yaml`:
    clips:
      - {file: mr_age.m4a, lang: mr, text: "लाडकी बहीण योजनेसाठी वयाची अट काय आहे?", family: false, require: [["21"]]}
or, per clip, a `<name>.txt` with the exact words spoken and a language prefix in the file name (mr_, hi_, en_).
`family: true` asks about the sample family (eval/fixtures/ask/sample_family.json); `require` (optional): groups of
alternatives that must appear in the answer.

Each clip goes the way the app sends it: converted by app/audio.py (ffmpeg), transcribed with the language bias
(and keywords only for ASR_KEYWORD_LANGUAGES), never cached. Reported per language: word error rate (WER) and
character error rate (CER) after normalizing punctuation, case and digits; the time to transcribe; and "right answer":
the answer to the transcript has the same kind as the answer to the exact words, and contains every `require` group
(without `require`: the same numbers and schemes as the answer to the exact words).
Results -> eval/results/asr_<timestamp>.json (references, transcripts, answers).
"""

import argparse
import json
import re
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from agents.ask_check import _schemes_in, answer_numbers  # noqa: E402
from agents.ask_tools import FamilyContext  # noqa: E402
from app.api.ask import _keywords  # noqa: E402
from app.audio import to_wav16k  # noqa: E402
from app.config import get_settings  # noqa: E402
from clients.transcribe import EVAL_SETTINGS, transcribe  # noqa: E402

AUDIO = {".wav", ".webm", ".m4a", ".mp4", ".ogg", ".mp3", ".aac"}
RESULTS = ROOT / "eval" / "results"
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

SYNTHETIC = [  # spoken by MMS-TTS; mixed speech is written in Devanagari (the voices read only their own script)
    {"lang": "mr", "text": "लाडकी बहीण योजनेसाठी वयाची अट काय आहे?", "family": False, "require": [["21"]]},
    {"lang": "mr", "text": "सविता यांचे आधार कार्ड पुन्हा का लागते?", "family": True, "require": [["फोटो"]]},
    {"lang": "mr", "text": "आदित्य यांना नवीन उत्पन्नाचा दाखला कुठे मिळेल?", "family": True, "require": [["तहसील", "आपले सरकार"]]},
    {"lang": "mr", "text": "लाडकी बहीण साठी इन्कम लिमिट किती आहे?", "family": False, "require": [["2,50,000", "250000", "2.5"]],
     "mixed": True},
    {"lang": "hi", "text": "लाडकी बहीण योजना में हर महीने कितने पैसे मिलते हैं?", "family": False, "require": [["1,500", "1500"]]},
    {"lang": "hi", "text": "लता के नाम की स्पेलिंग अलग क्यों है?", "family": True, "require": [["जाति", "स्पेलिंग"]]},
    {"lang": "hi", "text": "संजय गांधी निराधार योजना के लिए आय सीमा क्या है?", "family": False, "require": [["21,000", "21000"]]},
    {"lang": "hi", "text": "मेरी फैमिली के कौन से डॉक्युमेंट्स मिसिंग हैं?", "family": True, "require": [["फोटो", "फ़ोटो"]],
     "mixed": True},
    {"lang": "en", "text": "Who can apply for Ladki Bahin?", "family": False, "require": [["21"]]},
    {"lang": "en", "text": "Why does Savita need a clearer photo of her Aadhaar card?", "family": True, "require": [["photo"]]},
    {"lang": "en", "text": "How long does the new income certificate take?", "family": True, "require": [["15"]]},
    {"lang": "en", "text": "Where do I get a caste certificate?", "family": True, "require": [["Sub-Divisional", "office"]]},
]


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).translate(DIGITS).casefold().replace("़", "")  # nukta: ड़ = ड
    return [w for w in re.sub(r"[^\wऀ-ॿ]+", " ", text).split() if w]


def edits(ref: list, hyp: list) -> int:
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1]


def clips_from_folder(folder: Path) -> list[dict[str, Any]]:
    manifest = folder / "clips.yaml"
    if manifest.exists():
        clips = yaml.safe_load(manifest.read_text(encoding="utf-8"))["clips"]
        return [{**c, "path": folder / c["file"]} for c in clips]
    out = []
    for path in sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO):
        ref = path.with_suffix(".txt")
        lang = path.name.split("_", 1)[0]
        if ref.exists() and lang in get_settings().asr_language_names:
            out.append({"file": path.name, "path": path, "lang": lang, "text": ref.read_text(encoding="utf-8").strip(),
                        "family": False})
    return out


def synthetic_clips(folder: Path) -> list[dict[str, Any]]:
    """TTS each question, with silence around it as a person would leave, as WebM/Opus like Android Chrome sends."""
    import subprocess

    from clients.tts import synthesize

    out = []
    for n, c in enumerate(SYNTHETIC, 1):
        speech = synthesize(c["text"], c["lang"])
        path = folder / f"{c['lang']}_{n:02d}.webm"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(speech.path), "-af", "adelay=500,apad=pad_dur=1",
                        "-c:a", "libopus", str(path)], check=True)
        out.append({**c, "file": path.name, "path": path})
    return out


def answer_of(question: str, lang: str, family: bool, ctx: FamilyContext) -> Any:
    from agents.ask import ask

    return ask(question, lang, ctx.model_copy(deep=True) if family else None, timeout_s=60)


def right(ref_answer: Any, hyp_answer: Any, require: list[list[str]] | None) -> bool:
    if ref_answer.kind != hyp_answer.kind:
        return False
    text = hyp_answer.text.translate(DIGITS).casefold()
    if require:
        return all(any(r.casefold() in text for r in group) for group in require)
    return (answer_numbers(ref_answer.text) == answer_numbers(hyp_answer.text)
            and set(_schemes_in(ref_answer.text)) == set(_schemes_in(hyp_answer.text)))


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--clips", type=Path, help="folder of recordings")
    source.add_argument("--synthetic", action="store_true", help="MMS-TTS clips of 12 questions")
    parser.add_argument("--no-answers", action="store_true", help="recognition only")
    args = parser.parse_args()

    family = FamilyContext.model_validate_json((ROOT / "eval" / "fixtures" / "ask" / "sample_family.json")
                                               .read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="kaagaz-asr-") as tmp:
        clips = synthetic_clips(Path(tmp)) if args.synthetic else clips_from_folder(args.clips)
        if not clips:
            raise SystemExit("no clips found (see the usage at the top of this file)")
        rows = []
        for c in clips:
            wav, seconds = to_wav16k(c["path"].read_bytes(), get_settings().max_question_audio_s)
            keywords = _keywords(c["lang"], family if c.get("family") else None)  # exactly as the app sends them
            start = time.perf_counter()
            heard = transcribe(wav, c["lang"], keywords, cache=False, **EVAL_SETTINGS).text
            took = time.perf_counter() - start
            ref, hyp = normalize(c["text"]), normalize(heard)
            row = {"file": c["file"], "lang": c["lang"], "mixed": c.get("mixed", False), "reference": c["text"],
                   "heard": heard, "audio_s": round(seconds, 2), "transcribe_s": round(took, 2),
                   "word_errors": edits(ref, hyp), "words": len(ref),
                   "char_errors": edits(list("".join(ref)), list("".join(hyp))), "chars": len("".join(ref))}
            if not args.no_answers:
                a_ref = answer_of(c["text"], c["lang"], c.get("family", False), family)
                a_hyp = answer_of(heard, c["lang"], c.get("family", False), family)
                row.update({"answer_to_reference": a_ref.text, "answer_to_transcript": a_hyp.text,
                            "kinds": [a_ref.kind, a_hyp.kind], "right_answer": right(a_ref, a_hyp, c.get("require")),
                            "tokens": a_ref.usage.total_tokens + a_hyp.usage.total_tokens})
            rows.append(row)
            print(f"{c['file']:16} {c['lang']} WER {row['word_errors']}/{row['words']}  {took:4.1f}s  "
                  f"{'right' if row.get('right_answer') else '-' if args.no_answers else 'WRONG'}  {heard!r}")

    summary: dict[str, Any] = {"source": "synthetic (MMS-TTS)" if args.synthetic else str(args.clips)}
    for lang in sorted({r["lang"] for r in rows}):
        rs = [r for r in rows if r["lang"] == lang]
        summary[lang] = {"clips": len(rs),
                         "wer": round(sum(r["word_errors"] for r in rs) / max(1, sum(r["words"] for r in rs)), 3),
                         "cer": round(sum(r["char_errors"] for r in rs) / max(1, sum(r["chars"] for r in rs)), 3),
                         "mean_transcribe_s": round(sum(r["transcribe_s"] for r in rs) / len(rs), 2),
                         **({} if args.no_answers else {"right_answers": f"{sum(r['right_answer'] for r in rs)}/{len(rs)}"})}
    if not args.no_answers:
        summary["baseten_tokens"] = sum(r["tokens"] for r in rows)
    summary["audio_minutes"] = round(sum(r["audio_s"] for r in rows) / 60, 2)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"asr_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
