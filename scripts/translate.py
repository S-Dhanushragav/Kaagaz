"""Translation pipeline (Phase 11): every UI string and template, from English into a new language.

1. Muse Spark (Meta Model API) translates in chunks, with a fixed glossary (the app's name, document, office and scheme
   names) and placeholders kept as labels.
2. Muse Spark Open (Baseten) back-translates each string into English, literally.
3. Code checks each string: placeholders (each {name} as often as in the source), digits and amounts, the app's name,
   and that it is written in the language's script. Muse Spark Open then compares the meaning of each back-translation
   with the English source.
4. Reviewed corrections in data/translations/fixes.yaml replace a string (and are back-translated and checked again).

Outputs: data/templates/{ask,reasons,voice}/<lang>.yaml, frontend/src/locales/<lang>.ts, the scheme names and benefit
lines in data/schemes/*.yaml, and eval/results/translation_<lang>_<timestamp>.json with every check and mismatch.
Every model call goes through clients/llm.py (disk-cached: a re-run costs nothing unless a source string changed).

Usage (repo root, backend venv):
    python scripts/translate.py --languages ta te kn
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend")]

from app.config import get_settings  # noqa: E402
from clients.llm import complete  # noqa: E402
from schemas.languages import ENGLISH_NAMES, SCRIPT  # noqa: E402

PROMPTS = ROOT / "backend" / "prompts"
TEMPLATES = ROOT / "data" / "templates"
SCHEMES = ROOT / "data" / "schemes"
LOCALES = ROOT / "frontend" / "src" / "locales"
FIXES = ROOT / "data" / "translations" / "fixes.yaml"
RESULTS = ROOT / "eval" / "results"
CHUNK = 20
SCRIPT_NAMES = {"ta": "Tamil", "te": "Telugu", "kn": "Kannada", "ml": "Malayalam", "pa": "Gurmukhi"}

# Fixed terms. The app's name is the UI's own spelling; office names of Maharashtra are transliterated (the family will
# see them in Marathi at the office), document names are the usual official terms of each state.
GLOSSARY: dict[str, dict[str, str]] = {
    "ta": {"Kaagaz": "காகஸ்", "Aadhaar card": "ஆதார் அட்டை", "ration card": "ரேஷன் அட்டை",
           "income certificate": "வருமானச் சான்றிதழ்", "caste certificate": "சாதிச் சான்றிதழ்",
           "scheme": "திட்டம்", "Aadhaar Seva Kendra": "ஆதார் சேவை மையம்", "Tahsil office": "தஹசீல் அலுவலகம்",
           "Aaple Sarkar": "ஆப்லே சர்கார்", "supply office": "வழங்கல் அலுவலகம்", "office": "அலுவலகம்"},
    "te": {"Kaagaz": "కాగజ్", "Aadhaar card": "ఆధార్ కార్డు", "ration card": "రేషన్ కార్డు",
           "income certificate": "ఆదాయ ధృవీకరణ పత్రం", "caste certificate": "కుల ధృవీకరణ పత్రం",
           "scheme": "పథకం", "Aadhaar Seva Kendra": "ఆధార్ సేవా కేంద్రం", "Tahsil office": "తహసీల్ కార్యాలయం",
           "Aaple Sarkar": "ఆప్లే సర్కార్", "supply office": "సరఫరా కార్యాలయం", "office": "కార్యాలయం"},
    "kn": {"Kaagaz": "ಕಾಗಜ್", "Aadhaar card": "ಆಧಾರ್ ಕಾರ್ಡ್", "ration card": "ರೇಷನ್ ಕಾರ್ಡ್",
           "income certificate": "ಆದಾಯ ಪ್ರಮಾಣಪತ್ರ", "caste certificate": "ಜಾತಿ ಪ್ರಮಾಣಪತ್ರ",
           "scheme": "ಯೋಜನೆ", "Aadhaar Seva Kendra": "ಆಧಾರ್ ಸೇವಾ ಕೇಂದ್ರ", "Tahsil office": "ತಹಸೀಲ್ ಕಚೇರಿ",
           "Aaple Sarkar": "ಆಪ್ಲೆ ಸರ್ಕಾರ್", "supply office": "ಸರಬರಾಜು ಕಚೇರಿ", "office": "ಕಚೇರಿ"},
}
# Other ways a model may name the app; an Ask answer using one is rejected (agents/ask_check.py). The words for
# "paper" (காகிதம், కాగితం, ಕಾಗದ) are fine: Kannada ಕಾಗದ is the everyday word for the papers the answers are about, so
# unlike Marathi कागद it is not rejected (reviewed: it would reject right answers about an unidentified paper).
BRAND_WRONG: dict[str, list[str]] = {
    "ta": ["காகஜ்", "காகாஸ்", "காக்ஸ்", r"(?i)\bkaa?gh?aa?[zdj]\b"],
    "te": ["కాగజు", "కాగాజ్", "కాగస్", r"(?i)\bkaa?gh?aa?[zdj]\b"],
    "kn": ["ಕಾಗಜು", "ಕಾಗಾಜ್", "ಕಾಗಸ್", r"(?i)\bkaa?gh?aa?[zdj]\b"],
}
NOT_SURE_DROP = {"te": ["అర్థం కాలేదు"]}  # 'I did not understand' is not 'not sure' (reviewed)
KEEP = ("SPECIMEN", "SAM 3.1", "Muse Spark", "MMS-TTS")
PLACEHOLDER = re.compile(r"\{[a-z_0-9]+\}")
DIGITS = re.compile(r"\d[\d,]*")


# ---------- sources ----------

def flatten(value: Any, prefix: str) -> dict[str, str]:
    if isinstance(value, str):
        return {prefix: value}
    if isinstance(value, list):
        return {k: v for i, x in enumerate(value) for k, v in flatten(x, f"{prefix}.{i}").items()}
    if isinstance(value, dict):
        return {k: v for key, x in value.items() for k, v in flatten(x, f"{prefix}.{key}").items()}
    return {}


def unflatten(flat: dict[str, str], shape: Any, prefix: str) -> Any:
    """`shape` (the English structure) with every string replaced from `flat`."""
    if isinstance(shape, str):
        return flat[prefix]
    if isinstance(shape, list):
        return [unflatten(flat, x, f"{prefix}.{i}") for i, x in enumerate(shape)]
    return {k: unflatten(flat, v, f"{prefix}.{k}") for k, v in shape.items()}


def ui_source() -> dict[str, Any]:
    code = ("Promise.all([import('./src/i18n.ts'), import('./src/counts.ts')])"
            ".then(([i, c]) => console.log(JSON.stringify({ui: i.STRINGS.en, counts: c.FORMS.en})))")
    out = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", code], cwd=ROOT / "frontend",
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


VOICE_TEXT = ("documents", "unverified", "household", "not_on_card", "card_member", "options", "law_sets", "procedures",
              "ask_at_office", "questions")


def sources() -> tuple[dict[str, str], dict[str, Any]]:
    """(key -> English text, the English shapes to rebuild each output from)."""
    ui = ui_source()
    ask = load_yaml(TEMPLATES / "ask" / "en.yaml")
    reasons = load_yaml(TEMPLATES / "reasons" / "en.yaml")
    voice = load_yaml(TEMPLATES / "voice" / "en.yaml")
    shown = voice.get("values", {})
    values = {k: shown.get(k, k) for k in load_yaml(TEMPLATES / "voice" / "mr.yaml")["values"]}  # knowledge-base values
    schemes = {p.stem: load_yaml(p) for p in sorted(SCHEMES.glob("*.yaml")) if not p.stem.startswith("_")}
    shapes = {"ui": ui["ui"], "counts": ui["counts"],
              "ask": {k: ask[k] for k in ("replies", "lines", "chips", "suggestions")},
              "reasons": {k: v for k, v in reasons.items() if k != "language"},
              "voice": {k: voice[k] for k in VOICE_TEXT}, "values": values}
    flat: dict[str, str] = {}
    for name, shape in shapes.items():
        flat.update(flatten(shape, "voice" if name == "voice" else name) if name != "values" else
                    {f"voice.values.{i}": v for i, v in enumerate(values.values())})
    for sid, s in schemes.items():
        flat[f"scheme.{sid}.benefit"] = s["benefit"]["text"]["en"]
    return flat, {**shapes, "schemes": schemes, "voice_en": voice}


# ---------- model calls ----------

def ask_json(prompt: str, *, provider: str, max_tokens: int = 16000) -> dict[str, Any]:
    s = get_settings()
    # low reasoning effort: translation needs the tokens for the reply (Muse Spark otherwise reasons the budget away)
    overrides = ({"provider": "meta", "model": s.meta_agent_model, "reasoning_effort": "low"} if provider == "meta"
                 else {"provider": "baseten", "reasoning_effort": "low"})
    resp = complete(prompt, task="text", overrides=overrides, max_tokens=max_tokens,
                    response_format={"type": "json_object"})
    text = resp.text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])


def fill(template: str, **values: str) -> str:
    for k, v in values.items():
        template = template.replace("{" + k + "}", v)
    return template


def chunks(items: dict[str, str], size: int = CHUNK) -> list[dict[str, str]]:
    keys = list(items)
    return [{k: items[k] for k in keys[i:i + size]} for i in range(0, len(keys), size)]


def scheme_names(lang: str, schemes: dict[str, Any]) -> dict[str, dict[str, str]]:
    items = {sid: {"name": s["name"]["mr"], "short": s["short"]["mr"], "en": s["short"]["en"]} for sid, s in schemes.items()}
    prompt = fill((PROMPTS / "transliterate_schemes.md").read_text(encoding="utf-8"), language_name=ENGLISH_NAMES[lang],
                  script=SCRIPT_NAMES[lang], items=json.dumps(items, ensure_ascii=False, indent=1))
    return ask_json(prompt, provider="meta")


def glossary_text(lang: str, names: dict[str, dict[str, str]], schemes: dict[str, Any]) -> str:
    lines = [f'   - "{en}" -> "{x}"' for en, x in GLOSSARY[lang].items()]
    for sid, n in names.items():
        en = schemes[sid]["short"]["en"]
        lines.append(f'   - the scheme "{schemes[sid]["name"]["en"]}" / "{en}" -> "{n["short"]} ({en})" the first time it '
                     f'appears in a string, then "{n["short"]}"')
    return "\n".join(lines)


def translate(lang: str, items: dict[str, str], glossary: str) -> dict[str, str]:
    template = (PROMPTS / "translate.md").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for part in chunks(items):
        prompt = fill(template, language_name=ENGLISH_NAMES[lang], script=SCRIPT_NAMES[lang], brand=GLOSSARY[lang]["Kaagaz"],
                      glossary=glossary, items=json.dumps(part, ensure_ascii=False, indent=1))
        got = ask_json(prompt, provider="meta")
        out.update({k: str(got[k]) for k in part if k in got and isinstance(got[k], (str, int, float))})
        missing = [k for k in part if k not in out]
        if missing:  # once more, only the missing keys
            got = ask_json(fill(template, language_name=ENGLISH_NAMES[lang], script=SCRIPT_NAMES[lang],
                                brand=GLOSSARY[lang]["Kaagaz"], glossary=glossary,
                                items=json.dumps({k: part[k] for k in missing}, ensure_ascii=False, indent=1)),
                           provider="meta")
            out.update({k: str(got[k]) for k in missing if k in got})
        print(f"  {lang}: translated {len(out)}/{len(items)}", flush=True)
    return out


def back_translate(lang: str, items: dict[str, str]) -> dict[str, str]:
    template = (PROMPTS / "back_translate.md").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for part in chunks(items):
        got = ask_json(fill(template, language_name=ENGLISH_NAMES[lang], items=json.dumps(part, ensure_ascii=False, indent=1)),
                       provider="baseten")
        out.update({k: str(v) for k, v in got.items() if k in part})
    return out


def compare(lang: str, source: dict[str, str], back: dict[str, str]) -> dict[str, dict[str, Any]]:
    template = (PROMPTS / "compare_translation.md").read_text(encoding="utf-8")
    items = {k: {"source": source[k], "back": back.get(k, "")} for k in source}
    out: dict[str, dict[str, Any]] = {}
    for part in chunks(items, 40):
        got = ask_json(fill(template, language_name=ENGLISH_NAMES[lang], items=json.dumps(part, ensure_ascii=False, indent=1)),
                       provider="baseten")
        out.update({k: v for k, v in got.items() if k in part and isinstance(v, dict)})
    return out


def number_words(lang: str) -> dict[str, Any]:
    prompt = fill((PROMPTS / "number_words.md").read_text(encoding="utf-8"), language_name=ENGLISH_NAMES[lang],
                  script=SCRIPT_NAMES[lang])
    got = ask_json(prompt, provider="meta")
    assert len(got["words"]) == 100 and len(got["hundreds"]) == 9 and len(got["months"]) == 12, "number words incomplete"
    assert len(got["labels"]) == 5 and len(got["answer_numbers"]) == 5, "answer words incomplete"
    strip = lambda w: str(w).strip().strip("।.!?,")  # noqa: E731 - words a spoken answer is matched against
    got["answer_numbers"] = [[strip(w) for w in ws] for ws in got["answer_numbers"]]
    got["not_sure"] = [strip(w) for w in got["not_sure"] if not any(d in str(w) for d in NOT_SURE_DROP.get(lang, ()))]
    return got


# ---------- checks (code) ----------

def code_checks(lang: str, source: str, text: str) -> list[str]:
    problems = []
    if sorted(PLACEHOLDER.findall(source)) != sorted(PLACEHOLDER.findall(text)):
        problems.append(f"placeholders {sorted(PLACEHOLDER.findall(source))} -> {sorted(PLACEHOLDER.findall(text))}")
    digits = lambda s: sorted(d.replace(",", "") for d in DIGITS.findall(PLACEHOLDER.sub("", s)))  # noqa: E731
    if digits(source) != digits(text):
        problems.append(f"numbers {digits(source)} -> {digits(text)}")
    stem = GLOSSARY[lang]["Kaagaz"].rstrip("்్್")  # inflected forms drop the final virama
    if "Kaagaz" in source and stem not in text:
        problems.append("the app's name is not " + GLOSSARY[lang]["Kaagaz"])
    if any(re.search(rx, text) for rx in BRAND_WRONG[lang]):
        problems.append("the app's name is misspelled")
    if re.search(r"[.:?]", source) and not re.search(r"[.:?।]", text):
        problems.append("punctuation dropped")
    for keep in KEEP:
        if keep in source and keep not in text:
            problems.append(f"'{keep}' changed")
    bare = PLACEHOLDER.sub("", text)
    for keep in KEEP:
        bare = bare.replace(keep, "")
    own = len(re.findall(f"[{SCRIPT[lang]}]", bare))
    latin = len(re.findall(r"[A-Za-z]", bare))
    if own + latin and own < latin:
        problems.append("mostly not in the language's script")
    return problems


# ---------- outputs ----------

HEADER = ("# MACHINE-TRANSLATED by scripts/translate.py (Muse Spark; back-translated and checked with Muse Spark Open).\n"
          "# Not reviewed by a native speaker yet. Corrections go in data/translations/fixes.yaml, then re-run.\n")


def dump(path: Path, data: Any, comment: str = "") -> None:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False)
    path.write_text(HEADER + comment + text, encoding="utf-8", newline="\n")


def write_outputs(lang: str, flat: dict[str, str], shapes: dict[str, Any], names: dict[str, dict[str, str]],
                  numbers: dict[str, Any]) -> None:
    ask_en = load_yaml(TEMPLATES / "ask" / "en.yaml")
    ask = {"language": lang, "brand": GLOSSARY[lang]["Kaagaz"], "brand_wrong": BRAND_WRONG[lang],
           **unflatten(flat, shapes["ask"], "ask")}
    assert set(ask) >= set(ask_en) - {"language"}
    dump(TEMPLATES / "ask" / f"{lang}.yaml", ask, "# Placeholders stay labels (\"{member}: ...\"): no case endings on them.\n")
    dump(TEMPLATES / "reasons" / f"{lang}.yaml", {"language": lang, **unflatten(flat, shapes["reasons"], "reasons")})
    voice = {"language": lang, **unflatten(flat, shapes["voice"], "voice"),
             "values": {k: flat[f"voice.values.{i}"] for i, k in enumerate(shapes["values"])},
             "numbers": {k: numbers[k] for k in ("words", "hundreds", "thousand", "century", "months")},
             "answers": {"labels": numbers["labels"], "option": numbers["option"], "instruction": numbers["instruction"],
                         "retry": numbers["retry"], "buttons": numbers["buttons"],
                         "numbers": numbers["answer_numbers"], "not_sure": numbers["not_sure"]}}
    dump(TEMPLATES / "voice" / f"{lang}.yaml", voice, "# Placeholders: {office} {bring} {fee} {time_limit} {caution} {member} "
                                                     "{documents}. numbers/answers: spoken words (Muse Spark).\n")
    ui = unflatten(flat, shapes["ui"], "ui")
    counts = unflatten(flat, shapes["counts"], "counts")
    LOCALES.mkdir(parents=True, exist_ok=True)
    body = json.dumps(ui, ensure_ascii=False, indent=2)
    (LOCALES / f"{lang}.ts").write_text(
        "// MACHINE-TRANSLATED by scripts/translate.py (Muse Spark; back-translated and checked with Muse Spark Open).\n"
        "// Not reviewed by a native speaker. Do not edit by hand: corrections go in data/translations/fixes.yaml.\n"
        "import type { Forms, Noun } from '../counts'\nimport type { Strings } from '../i18n'\n\n"
        f"export const strings: Strings = {body}\n\n"
        f"export const counts: Record<Noun, Forms> = {json.dumps(counts, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8", newline="\n")
    for sid, s in shapes["schemes"].items():
        path = SCHEMES / f"{sid}.yaml"
        text = path.read_text(encoding="utf-8")
        en = s["short"]["en"]
        text = _set_lang(text, "name", lang, f'{names[sid]["name"]} ({en})')
        text = _set_lang(text, "short", lang, names[sid]["short"])
        text = _set_lang(text, "  text", lang, flat[f"scheme.{sid}.benefit"])
        path.write_text(text, encoding="utf-8", newline="\n")


def _set_lang(text: str, field: str, lang: str, value: str) -> str:
    """Add or replace `lang: "value"` in a one-line flow mapping (`name: {en: "...", mr: "..."}`), keeping comments."""
    line = re.search(rf"^{field}: \{{(.*)\}}$", text, re.MULTILINE)
    assert line, f"no one-line {field} mapping"
    pairs = [p for p in re.findall(r'(\w+): ("(?:[^"\\]|\\.)*")', line.group(1)) if p[0] != lang]
    pairs.append((lang, json.dumps(value, ensure_ascii=False)))
    return text[:line.start()] + f"{field}: {{" + ", ".join(f"{k}: {v}" for k, v in pairs) + "}" + text[line.end():]


# ---------- main ----------

def run(lang: str) -> dict[str, Any]:
    source, shapes = sources()
    print(f"{lang}: {len(source)} strings", flush=True)
    names = scheme_names(lang, shapes["schemes"])
    glossary = glossary_text(lang, names, shapes["schemes"])
    first = translate(lang, source, glossary)
    fixes = (load_yaml(FIXES) or {}).get(lang, {}) if FIXES.exists() else {}
    final = {**first, **{k: v["text"] for k, v in fixes.items() if k in source}}
    missing = [k for k in source if k not in final]
    if missing:
        raise SystemExit(f"{lang}: no translation for {missing}")
    back = back_translate(lang, final)
    meaning = compare(lang, source, back)
    numbers = number_words(lang)
    rows = []
    for k, src in source.items():
        problems = code_checks(lang, src, final[k])
        m = meaning.get(k, {"same": None})
        rows.append({"key": k, "source": src, "translation": final[k], "back": back.get(k), "code": problems,
                     "same_meaning": m.get("same"), "difference": m.get("difference"),
                     "fixed": fixes.get(k, {}).get("why") if k in fixes else None,
                     "first_translation": first.get(k) if k in fixes else None})
    write_outputs(lang, final, shapes, names, numbers)
    report = {"language": lang, "strings": len(rows), "scheme_names": names, "number_words": numbers,
              "code_failures": sum(1 for r in rows if r["code"]),
              "meaning_mismatches": sum(1 for r in rows if r["same_meaning"] is False),
              "fixed": sum(1 for r in rows if r["fixed"]), "rows": rows}
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"translation_{lang}_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{lang}: {report['code_failures']} code failures, {report['meaning_mismatches']} meaning mismatches, "
          f"{report['fixed']} fixed -> {out.relative_to(ROOT)}", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--languages", nargs="+", default=["ta", "te", "kn"])
    args = parser.parse_args()
    for lang in args.languages:
        if lang not in GLOSSARY:
            raise SystemExit(f"no glossary for {lang}")
        run(lang)


if __name__ == "__main__":
    main()
