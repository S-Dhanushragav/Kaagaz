"""Speech text: numbers and dates spelled out for TTS (en, hi, mr)."""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from agents.speech import date_words, number_words, speech_text, year_words
from agents.tools import load_fixes
from agents.voice import LANGUAGES, load_voice

EVAL = Path(__file__).resolve().parents[2] / "synthetic" / "eval_households"
DIGITS = re.compile(r"[0-9०-९]")  # ASCII and Devanagari digits


def _kb_numbers() -> set[int]:
    """Every number in the knowledge base's facts (fees, days)."""
    return {int(n) for p in load_fixes().values() for f in p.facts().values() for n in re.findall(r"\d+", f.value)}


def _eval_dobs() -> list[str]:
    out = []
    for path in sorted(EVAL.glob("EV*/ground_truth.json")):
        gt = json.loads(path.read_text(encoding="utf-8"))
        out += [datetime.strptime(m["dob"], "%Y-%m-%d").strftime("%d/%m/%Y") for m in gt["members"]]
    return out


@pytest.mark.parametrize("language", LANGUAGES)
def test_number_tables_are_complete_and_distinct(language: str) -> None:
    w = load_voice(language).numbers
    assert len(w.words) == 100 and len(set(w.words)) == 100
    assert len(w.hundreds) == 9 and len(w.months) == 12 and len(set(w.months)) == 12


@pytest.mark.parametrize("language, n, words", [
    ("en", 2, "two"), ("en", 15, "fifteen"), ("en", 75, "seventy-five"), ("en", 100, "one hundred"),
    ("en", 2026, "two thousand twenty-six"), ("en", 105, "one hundred five"),
    ("hi", 2, "दो"), ("hi", 15, "पंद्रह"), ("hi", 75, "पचहत्तर"), ("hi", 100, "एक सौ"), ("hi", 2026, "दो हज़ार छब्बीस"),
    ("mr", 2, "दोन"), ("mr", 15, "पंधरा"), ("mr", 75, "पंच्याहत्तर"), ("mr", 100, "शंभर"), ("mr", 2026, "दोन हजार सव्वीस"),
    ("mr", 250, "दोनशे पन्नास"),
])
def test_numbers(language: str, n: int, words: str) -> None:
    assert number_words(n, language) == words


@pytest.mark.parametrize("language, date, words", [
    ("en", "14/02/1978", "fourteen February nineteen hundred seventy-eight"),
    ("hi", "14/02/1978", "चौदह फ़रवरी उन्नीस सौ अठहत्तर"),
    ("mr", "14/02/1978", "चौदा फेब्रुवारी एकोणीसशे अठ्ठ्याहत्तर"),
    ("en", "05/02/1981", "five February nineteen hundred eighty-one"),
    ("hi", "01/01/2006", "एक जनवरी दो हज़ार छह"),
    ("mr", "31/12/1900", "एकतीस डिसेंबर एकोणीसशे"),
])
def test_dates(language: str, date: str, words: str) -> None:
    assert speech_text(date, language) == words


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_number_that_can_appear_is_spelled_out(language: str) -> None:
    numbers = _kb_numbers()
    assert {2, 15, 75} <= numbers
    for n in numbers:
        assert not DIGITS.search(number_words(n, language))
    dobs = _eval_dobs()
    assert len(dobs) > 100
    for dob in dobs:
        spoken = speech_text(f"Aadhaar card: {dob}", language)
        assert not DIGITS.search(spoken), spoken
        day, month, year = (int(x) for x in dob.split("/"))
        assert load_voice(language).numbers.months[month - 1] in spoken
        assert year_words(year, language) in spoken and date_words(day, month, year, language) in spoken


def test_rupees_and_screen_text() -> None:
    assert speech_text("Fee: about Rs 75.", "en") == "Fee: about seventy-five rupees."
    assert speech_text("शुल्क: लगभग 75 रुपये।", "hi") == "शुल्क: लगभग पचहत्तर रुपये।"
    assert speech_text("शुल्क: 2 रुपये.", "mr") == "शुल्क: दोन रुपये."
    assert speech_text("कायद्याने या कार्यालयासाठी 15 दिवस ठरवले आहेत.", "mr") == "कायद्याने या कार्यालयासाठी पंधरा दिवस ठरवले आहेत."
    assert speech_text("No numbers here.", "en") == "No numbers here."
    assert number_words(123456, "en") == "one two three four five six"  # out of range: digit by digit
