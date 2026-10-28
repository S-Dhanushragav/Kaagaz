"""Name matching across scripts: Devanagari -> Latin transliteration + rapidfuzz.

Used to decide WHICH member a document belongs to. Whether two spellings are identical is a separate,
exact check in the household builder: fuzzy matching links "Sunil" and "Suneel", and the spelling
check then reports them as a name mismatch.
"""

import re
import unicodedata
from typing import NamedTuple

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate
from rapidfuzz import fuzz

from vision.text import normalize_text

# IAST -> plain Latin as Marathi names are usually written in English.
_IAST = [
    ("jñ", "dny"),  # ज्ञ: Dnyaneshwar
    ("ṛ", "ru"),  # ऋ: Rugved, Rutuja
    ("ś", "sh"), ("ṣ", "sh"),
    ("ch", "\x01"), ("c", "ch"), ("\x01", "chh"),  # IAST c = च (ch), ch = छ (chh)
    ("ṃ", "n"), ("ṅ", "n"), ("ñ", "n"), ("ṇ", "n"),
    ("ḥ", ""), ("ḻ", "l"), ("ṟ", "r"), ("ṭ", "t"), ("ḍ", "d"),
]
_VOWELS = set("aeiou")


class NamePair(NamedTuple):
    mr: str | None
    en: str | None


def _strip_diacritics(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def simplify_latin(text: str) -> str:
    """Lower-case, no diacritics, letters and spaces only, common spelling variants folded."""
    s = _strip_diacritics(text).lower()
    s = re.sub(r"[^a-z ]+", " ", s)
    for a, b in (("ee", "i"), ("oo", "u"), ("aa", "a"), ("w", "v"), ("ph", "f")):
        s = s.replace(a, b)
    s = re.sub(r"([a-z])\1+", r"\1", s)  # doubled letters: Vitthal / Vithal
    return " ".join(s.split())


def devanagari_to_latin(text: str) -> str:
    """'सुनील रमेश पाटील' -> 'sunil ramesh patil' (approximate; for matching only)."""
    s = transliterate(normalize_text(text), sanscript.DEVANAGARI, sanscript.IAST)
    for a, b in _IAST:
        s = s.replace(a, b)
    words = []
    for w in _strip_diacritics(s).split():
        if len(w) > 2 and w.endswith("a") and w[-2] not in _VOWELS:
            w = w[:-1]  # Marathi drops the final inherent vowel: sunila -> sunil
        words.append(w)
    return simplify_latin(" ".join(words))


def _score(a: str, b: str) -> float:
    """Half the weight on the first word (the person's own given name), half on the whole name:
    family members share the middle name and surname, so whole-name similarity alone is too high."""
    if not a or not b:
        return 0.0
    first = fuzz.ratio(a.split()[0], b.split()[0])
    return 0.5 * first + 0.5 * fuzz.token_sort_ratio(a, b)


def name_score(a: NamePair, b: NamePair) -> float:
    """0-100: how likely two name records are the same person, across English, Marathi, and both."""
    scores = []
    if a.en and b.en:
        scores.append(_score(simplify_latin(a.en), simplify_latin(b.en)))
    if a.mr and b.mr:
        scores.append(_score(" ".join(normalize_text(a.mr).split()), " ".join(normalize_text(b.mr).split())))
        scores.append(_score(devanagari_to_latin(a.mr), devanagari_to_latin(b.mr)))  # सुनिल / सुनील
    if a.mr and b.en:
        scores.append(_score(devanagari_to_latin(a.mr), simplify_latin(b.en)))
    if a.en and b.mr:
        scores.append(_score(simplify_latin(a.en), devanagari_to_latin(b.mr)))
    return round(max(scores), 1) if scores else 0.0
