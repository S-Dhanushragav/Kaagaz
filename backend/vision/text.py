"""Text normalization shared by extraction (Phase 3 reader) and scoring."""

import re
import unicodedata

# An ASCII colon right after a Devanagari character that ends the string or is followed by
# another Devanagari character is almost always a misread visarga (स्वत: -> स्वतः, दु:ख -> दुःख).
# A colon followed by a space is left alone, since that is usually a label ("नाव: सुनील").
_COLON_AS_VISARGA = re.compile(r"(?<=[ऀ-ॿ]):(?=[ऀ-ॿ]|$)")


def normalize_text(text: str) -> str:
    """NFC-normalize and repair visargas misread as ASCII colons."""
    return _COLON_AS_VISARGA.sub("ः", unicodedata.normalize("NFC", text))
