"""Field-by-field scoring of extracted values against ground_truth.json document fields."""

from dataclasses import dataclass, field
from typing import Any, Iterator

from vision.text import comparison_key  # backend/ must be on sys.path


def normalize(value: Any) -> str:
    """Same rule the reader uses for frame agreement (vision.text.comparison_key)."""
    return comparison_key(value)


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


@dataclass
class FieldScore:
    """Three-way field result. A wrong value is worse than a null: it looks trustworthy."""

    correct: int = 0
    wrong: list[tuple[str, Any, Any]] = field(default_factory=list)  # (path, expected, got)
    null: list[tuple[str, Any]] = field(default_factory=list)  # (path, expected): missing or null

    @property
    def total(self) -> int:
        return self.correct + len(self.wrong) + len(self.null)

    def add(self, other: "FieldScore") -> None:
        self.correct += other.correct
        self.wrong += other.wrong
        self.null += other.null


def score_fields(expected: dict[str, Any], predicted: dict[str, Any] | None) -> FieldScore:
    """Score every expected field as correct, wrong value, or null. Lists align by index."""
    got = dict(flatten(predicted or {}))
    result = FieldScore()
    for path, value in flatten(expected):
        g = got.get(path)
        if g is None:
            result.null.append((path, value))
        elif matches(value, g):
            result.correct += 1
        else:
            result.wrong.append((path, value, g))
    return result


def score(expected: dict[str, Any], predicted: dict[str, Any]) -> tuple[int, int, list[tuple[str, Any, Any]]]:
    """Return (correct, total, not_correct) where not_correct lists (path, expected, got)."""
    s = score_fields(expected, predicted)
    not_correct = s.wrong + [(path, value, None) for path, value in s.null]
    return s.correct, s.total, not_correct
