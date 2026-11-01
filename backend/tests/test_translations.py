"""Every language's templates keep the English placeholders exactly, and the machine-translated ones keep amounts,
numbers and the scheme names (data/templates, data/schemes; written by scripts/translate.py)."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from rules.loader import load_schemes
from schemas.languages import LANGUAGES, MACHINE_TRANSLATED

TEMPLATES = Path(__file__).resolve().parents[2] / "data" / "templates"
PLACEHOLDER = re.compile(r"\{[a-z_0-9]+\}")
NUMBER = re.compile(r"\d[\d,]*")
VOICE_TEXT = ("documents", "unverified", "household", "not_on_card", "card_member", "options", "law_sets", "procedures",
              "ask_at_office", "questions")
OTHERS = [lang for lang in LANGUAGES if lang != "en"]


def flatten(value: Any, prefix: str = "") -> dict[str, str]:
    if isinstance(value, str):
        return {prefix: value}
    if isinstance(value, list):
        return {k: v for i, x in enumerate(value) for k, v in flatten(x, f"{prefix}.{i}").items()}
    if isinstance(value, dict):
        return {k: v for key, x in value.items() for k, v in flatten(x, f"{prefix}.{key}" if prefix else key).items()}
    return {}


def load(kind: str, lang: str) -> dict[str, Any]:
    return yaml.safe_load((TEMPLATES / kind / f"{lang}.yaml").read_text(encoding="utf-8"))


def texts(kind: str, lang: str) -> dict[str, str]:
    data = load(kind, lang)
    if kind == "ask":
        data = {k: data[k] for k in ("replies", "lines", "chips", "suggestions")}
    elif kind == "voice":
        data = {k: data[k] for k in VOICE_TEXT}
    else:
        data = {k: v for k, v in data.items() if k != "language"}
    return flatten(data)


def numbers(text: str) -> list[str]:
    return sorted(n.replace(",", "") for n in NUMBER.findall(PLACEHOLDER.sub("", text)))


@pytest.mark.parametrize("kind", ["ask", "reasons", "voice"])
@pytest.mark.parametrize("lang", OTHERS)
def test_every_template_keeps_the_english_placeholders(kind: str, lang: str) -> None:
    en, other = texts(kind, "en"), texts(kind, lang)
    assert sorted(other) == sorted(en), f"{lang} {kind}: keys differ"
    bad = {k: (PLACEHOLDER.findall(en[k]), PLACEHOLDER.findall(other[k])) for k in en
           if sorted(PLACEHOLDER.findall(en[k])) != sorted(PLACEHOLDER.findall(other[k]))}
    assert not bad, f"{lang} {kind}: missing or altered placeholders {bad}"


@pytest.mark.parametrize("kind", ["ask", "reasons", "voice"])
@pytest.mark.parametrize("lang", sorted(MACHINE_TRANSLATED))
def test_machine_translations_keep_every_number(kind: str, lang: str) -> None:
    en, other = texts(kind, "en"), texts(kind, lang)
    bad = {k: other[k] for k in en if numbers(en[k]) != numbers(other[k])}
    assert not bad, f"{lang} {kind}: numbers changed {bad}"


@pytest.mark.parametrize("lang", sorted(MACHINE_TRANSLATED))
def test_spoken_values_keep_amounts_and_days(lang: str) -> None:
    """Fees and time limits ('about Rs 75', '15 days') keep their digits on screen; speech spells them out."""
    values = load("voice", lang)["values"]
    for source, shown in values.items():
        assert numbers(shown) == numbers(source.replace("Rs ", "")), (source, shown)


@pytest.mark.parametrize("lang", sorted(MACHINE_TRANSLATED))
def test_scheme_names_transliterated_with_the_english_name_in_brackets(lang: str) -> None:
    reply = load("ask", lang)["replies"]["out_of_scope"]
    for s in load_schemes():
        assert s.name[lang].endswith(f"({s.short['en']})"), s.name[lang]
        assert not re.search("[A-Za-z]", s.short[lang]), s.short[lang]  # in the language's own script
        assert f"{s.short[lang]} ({s.short['en']})" in reply, (s.id, reply)  # first mention: with the English name
        assert s.benefit.text[lang]


def test_placeholder_check_fails_on_a_changed_placeholder() -> None:
    """The check above catches a translated or dropped placeholder."""
    en = "{member}: go to the {office}."
    for broken in ("{सदस्य}: {office} येथे जा.", "{office} येथे जा.", "{member}: {office}, {office}."):
        assert sorted(PLACEHOLDER.findall(en)) != sorted(PLACEHOLDER.findall(broken))
