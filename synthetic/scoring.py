"""Field-by-field scoring of extracted values against ground_truth.json document fields."""

import unicodedata
from typing import Any, Iterator

from vision.text import normalize_text  # backend/ must be on sys.path

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize(value: Any) -> str:
    """normalize_text (NFC, colon->visarga), Devanagari digits -> ASCII, casefold,
    drop whitespace and punctuation (incl. danda)."""
    s = normalize_text(str(value)).translate(_DEVANAGARI_DIGITS).casefold()
    return "".join(ch for ch in s if not ch.isspace() and not unicodedata.category(ch).startswith("P"))


def flatten(fields: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """{'members': [{'age': 3}]} -> ('members[0].age', 3)."""
    if isinstance(fields, dict):
        for k, v in fields.items():
            yield from flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(fields, list):
        for i, v in enumerate(fields):
            yield from flatten(v, f"{prefix}[{i}]")
    else:
        yield prefix, fields


def matches(expected: Any, got: Any) -> bool:
    if got is None:
        return False
    if isinstance(expected, int) and not isinstance(expected, bool):
        return "".join(ch for ch in normalize(got) if ch.isdigit()) == str(expected)
    return normalize(expected) == normalize(got)


def score(expected: dict[str, Any], predicted: dict[str, Any]) -> tuple[int, int, list[tuple[str, Any, Any]]]:
    """Return (correct, total, wrong) where wrong lists (path, expected, got). Lists align by index."""
    got = dict(flatten(predicted))
    correct, wrong = 0, []
    pairs = list(flatten(expected))
    for path, value in pairs:
        if matches(value, got.get(path)):
            correct += 1
        else:
            wrong.append((path, value, got.get(path)))
    return correct, len(pairs), wrong
