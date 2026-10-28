"""Text normalization and identity-number masking, shared by the reader and scoring."""

import re
import unicodedata

# An ASCII colon right after a Devanagari character that ends the string or is followed by
# another Devanagari character is almost always a misread visarga (स्वत: -> स्वतः, दु:ख -> दुःख).
# A colon followed by a space is left alone, since that is usually a label ("नाव: सुनील").
_COLON_AS_VISARGA = re.compile(r"(?<=[ऀ-ॿ]):(?=[ऀ-ॿ]|$)")

# 12 digits, optionally grouped 4-4-4 with spaces or dashes, not part of a longer number.
# Devanagari digits are included because the model may copy them as printed.
_D = r"[0-9०-९]"
_IDENTITY_NUMBER = re.compile(
    rf"(?<![0-9०-९])({_D}{{4}})[ \-]?({_D}{{4}})[ \-]?({_D}{{4}})(?![0-9०-९])"
)
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
MASKED_ID = re.compile(r"^XXXX XXXX \d{4}$")


def normalize_text(text: str) -> str:
    """NFC-normalize and repair visargas misread as ASCII colons."""
    return _COLON_AS_VISARGA.sub("ः", unicodedata.normalize("NFC", text))


def comparison_key(value: object) -> str:
    """Key for 'same value?' checks: normalize_text, Devanagari digits -> ASCII, casefold,
    no whitespace or punctuation (incl. danda). Used for frame agreement and eval scoring."""
    s = normalize_text(str(value)).translate(_DEVANAGARI_DIGITS).casefold()
    return "".join(ch for ch in s if not ch.isspace() and not unicodedata.category(ch).startswith("P"))


def mask_last4(last4: str) -> str:
    return f"XXXX XXXX {last4.translate(_DEVANAGARI_DIGITS)}"


def mask_identity_number(number: str) -> str:
    """'0123 4567 8901' / '012345678901' / '8901' -> 'XXXX XXXX 8901'. Raises if no 4+ digits."""
    digits = "".join(ch for ch in number.translate(_DEVANAGARI_DIGITS) if ch.isdigit())
    if len(digits) < 4:
        raise ValueError(f"Not an identity number: {number!r}")
    return mask_last4(digits[-4:])


def redact_identity_numbers(text: str) -> str:
    """Replace every 12-digit number (plain, or grouped with spaces/dashes) with its masked form."""
    return _IDENTITY_NUMBER.sub(lambda m: mask_last4(m.group(3)), text)
