"""The app's name in Ask answers: always the UI's own spelling (agents/ask_check.py, data/templates/ask)."""

import re
from pathlib import Path

import pytest

from agents.ask_check import Evidence, check
from agents.ask_tools import load_ask
from agents.voice import LANGUAGES

I18N = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n.ts"


def _brand_failures(text: str, language: str) -> list[str]:
    return [f for f in check(text, language, Evidence(used=[])) if "app's name" in f]


@pytest.mark.parametrize("text", [
    "कागदकडे याबद्दल माहिती नाही. कृपया कार्यालयात विचारा.",
    "कागद याबद्दल काही सांगू शकत नाही.",
    "मी कागद आहे. कार्यालयात विचारा.",
    "Kagaz कडे याची माहिती नाही.",
])
def test_marathi_answer_calling_the_app_kagad_is_rejected(text: str) -> None:
    assert _brand_failures(text, "mr") == ["The app's name is written कागज in this language: never any other spelling."]


@pytest.mark.parametrize("text", [
    "कागजकडे याबद्दल माहिती नाही. कृपया कार्यालयात विचारा.",
    "तुमच्या कागदपत्रांनुसार काही अडचण नाही.",
    "या कागदावर नाव वेगळे आहे.",  # 'on this paper': an inflected noun, not the app
])
def test_marathi_answer_with_the_ui_spelling_or_the_word_paper_passes(text: str) -> None:
    assert _brand_failures(text, "mr") == []


def test_hindi_and_english_spellings() -> None:
    assert _brand_failures("कागद के पास इसकी जानकारी नहीं है।", "hi")
    assert not _brand_failures("कागज़ के पास इसकी जानकारी नहीं है।", "hi")
    assert _brand_failures("Kagaz has no information on this.", "en")
    assert not _brand_failures("Kaagaz has no information on this.", "en")


@pytest.mark.parametrize("language", LANGUAGES)
def test_brand_is_the_ui_app_name(language: str) -> None:
    """The templates' brand is exactly the app name the UI shows in that language."""
    source = I18N.read_text(encoding="utf-8")
    block = source if language == "en" else source[source.index(f"const {language}: Strings = {{"):]
    shown = re.search(r"appName: '([^']+)'", block).group(1)
    assert load_ask(language).brand == shown
