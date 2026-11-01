"""Speech text: the TTS input for a sentence, with numbers and dates spelled out in words.

Screen text keeps digits; only what goes to TTS is spelled out. Deterministic. Word tables live in
data/templates/voice/<language>.yaml (`numbers`), so a native speaker can review all wording in one place.
Covers 0-9999 and dates DD/MM/YYYY (day, month name, year; years 1100-1999 as '<19> hundred <81>').
The Tamil, Telugu and Kannada voices read only their own script, so names (shown in Latin letters, or Devanagari) are
written in that script for them (`say_in_script`): for the voice only, never on screen.
"""

import re

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

from agents.voice import NumberWords, load_voice

DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
RUPEES = re.compile(r"(?:\bRs\.?\s*|₹\s*)(\d[\d,]*)\b")  # 'Rs 75', '₹75', '₹2,04,000'
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


SCRIPTS = {"ta": sanscript.TAMIL, "te": sanscript.TELUGU, "kn": sanscript.KANNADA}
VIRAMA = {"ta": "்", "te": "్", "kn": "್"}
DEVANAGARI_WORD = re.compile(r"[ऀ-ॿ]+")
LATIN_WORD = re.compile(r"[A-Za-z]+")
BRACKETED_LATIN = re.compile(r"\s*\([A-Za-z][A-Za-z .'-]*\)")
CONSONANT = re.compile(r"[क-हक़-य़]$")
# letters the Tamil voice has no symbol for -> the nearest one it has
TAMIL_VOICE = str.maketrans({"ஶ": "ஷ", "ஂ": "ம்"})


def _from_devanagari(word: str, language: str) -> str:
    out = transliterate(word, sanscript.DEVANAGARI, SCRIPTS[language])
    if CONSONANT.search(word):  # Marathi and Hindi drop a name's final 'a' (पवार: Pawar)
        out += VIRAMA[language]
    return out.translate(TAMIL_VOICE) if language == "ta" else out


def _from_latin(word: str) -> str:
    """A name in Latin letters, as the Devanagari it most likely sounds like (ITRANS; a final 'a' is long: Savita)."""
    w = re.sub(r"a$", "A", word.lower().replace("w", "v").replace("ee", "I").replace("oo", "U"))
    return transliterate(w, sanscript.ITRANS, sanscript.DEVANAGARI)


def say_in_script(text: str, language: str) -> str:
    """Devanagari and Latin words written in the language's own script, for a Tamil, Telugu or Kannada voice."""
    if language not in SCRIPTS:
        return text
    text = BRACKETED_LATIN.sub("", text)  # 'லாட்கி பஹிண் (Ladki Bahin)': the English name is for reading only
    text = DEVANAGARI_WORD.sub(lambda m: _from_devanagari(m.group(), language), text)
    return LATIN_WORD.sub(lambda m: _from_devanagari(_from_latin(m.group()), language), text)


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
        text = RUPEES.sub(lambda m: w.rupees.format(n=m.group(1).replace(",", "")), text)
    return say_in_script(NUMBER.sub(lambda m: number_words(int(m.group()), language), text), language)
