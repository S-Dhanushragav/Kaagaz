"""The app's languages, and which script a family's names are shown in.

Documents stay Marathi (names in Devanagari, and in Latin letters on the Aadhaar card). Hindi and Marathi show names
in Devanagari; every other language shows them in Latin letters as printed on the documents, never a machine
transliteration (the app is about spellings, so it never makes up a new one). Speech says them in the language's own
script (agents/speech.py `say_names`).
"""

from typing import Literal, get_args

Language = Literal["en", "hi", "mr", "ta", "te", "kn"]
LANGUAGES: tuple[str, ...] = get_args(Language)
ENGLISH_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "kn": "Kannada"}
# Unicode block of each language's script (letters, vowel signs and digits)
SCRIPT = {"en": "A-Za-z", "hi": "\u0900-\u097f", "mr": "\u0900-\u097f", "ta": "\u0b80-\u0bff",
          "te": "\u0c00-\u0c7f", "kn": "\u0c80-\u0cff"}
INDIC = "\u0900-\u0d7f"  # every Indic script block from Devanagari to Malayalam (for word boundaries)
MACHINE_TRANSLATED = frozenset({"ta", "te", "kn"})  # not reviewed by a native speaker yet


def devanagari_names(language: str) -> bool:
    """Names in Devanagari (hi, mr); otherwise in Latin letters as on the documents."""
    return language in ("hi", "mr")
