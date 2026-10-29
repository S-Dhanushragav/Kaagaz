"""Speech text: the TTS input for a sentence, with numbers and dates spelled out in words.

Screen text keeps digits; only what goes to TTS is spelled out. Deterministic. Word tables live in
data/templates/voice/{en,hi,mr}.yaml (`numbers`), so a native speaker can review all wording in one place.
Covers 0-9999 and dates DD/MM/YYYY (day, month name, year; years 1100-1999 as '<19> hundred <81>').
"""

import re

from agents.voice import NumberWords, load_voice

DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
RUPEES = re.compile(r"\bRs\.?\s*(\d+)\b")
NUMBER = re.compile(r"\d+")


def number_words(n: int, language: str) -> str:
    w = load_voice(language).numbers
    if not 0 <= n <= 9999:
        return " ".join(w.words[int(d)] for d in str(n))  # digit by digit
    return _cardinal(n, w)


def _cardinal(n: int, w: NumberWords) -> str:
    if n < 100:
        return w.words[n]
    if n < 1000:
        h, rest = divmod(n, 100)
        return w.hundreds[h - 1] + (f" {w.words[rest]}" if rest else "")
    t, rest = divmod(n, 1000)
    return f"{w.words[t]} {w.thousand}" + (f" {_cardinal(rest, w)}" if rest else "")


def year_words(year: int, language: str) -> str:
    w = load_voice(language).numbers
    if 1100 <= year <= 1999:
        century, rest = divmod(year, 100)
        return w.century.format(n=w.words[century]) + (f" {w.words[rest]}" if rest else "")
    return number_words(year, language)


def date_words(day: int, month: int, year: int, language: str) -> str:
    w = load_voice(language).numbers
    return f"{number_words(day, language)} {w.months[month - 1]} {year_words(year, language)}"


def speech_text(text: str, language: str) -> str:
    """`text` with every date and number spelled out (and 'Rs 75' as '75 rupees' in English)."""
    w = load_voice(language).numbers

    def date(m: re.Match) -> str:
        day, month, year = (int(g) for g in m.groups())
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return " / ".join(number_words(int(g), language) for g in m.groups())
        return date_words(day, month, year, language)

    text = DATE.sub(date, text)
    if w.rupees:
        text = RUPEES.sub(lambda m: w.rupees.format(n=m.group(1)), text)
    return NUMBER.sub(lambda m: number_words(int(m.group()), language), text)
