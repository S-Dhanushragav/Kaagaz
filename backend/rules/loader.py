"""Load scheme rules from data/schemes/*.yaml into validated models.

Rule values are written by the developer from official sources; this loader only checks their
shape: every rule needs a value, a status, a source, and a last-checked date.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

SCHEMES_DIR = Path(__file__).resolve().parents[2] / "data" / "schemes"

Check = Literal[
    "gender", "age_min", "age_max", "age_below", "income_max", "income_bands",
    "caste_household", "caste_applicant", "documents", "income_certificate_unless_card",
    "issued_this_financial_year",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportedValue(_Strict):
    value: Any
    area: str | None = None
    source: str
    source_url: str | None


class Rule(_Strict):
    id: str
    check: Check
    value: Any
    status: Literal["verified", "conflict", "unverified"]
    source: str
    source_url: str | None
    last_checked: date
    interpretation: str | None = None  # our reading where the source's text does not settle it
    reported: list[ReportedValue] = []  # for status: conflict
    note: str | None = None


class OtherProof(_Strict):
    id: str
    text: str
    status: Literal["verified", "conflict", "unverified"]
    source: str
    source_url: str | None
    last_checked: date


class Benefit(_Strict):
    """A one-line benefit shown in the app (not used by the rules)."""

    text: dict[str, str]  # by language
    status: Literal["verified", "conflict", "unverified"]
    source: str
    source_url: str | None
    last_checked: date


class Scheme(_Strict):
    id: str
    name: dict[str, str]  # full name by language
    short: dict[str, str]  # short name by language (the household matrix)
    benefit: Benefit
    rules: list[Rule]
    needs_other_proof: list[OtherProof] = []


class SharedRules(_Strict):
    id: Literal["_shared"]
    rules: list[Rule]

    def rule(self, rule_id: str) -> Rule:
        return next(r for r in self.rules if r.id == rule_id)


def _read(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache
def load_schemes(directory: Path = SCHEMES_DIR) -> tuple[Scheme, ...]:
    return tuple(Scheme.model_validate(_read(p)) for p in sorted(directory.glob("*.yaml")) if not p.name.startswith("_"))


@lru_cache
def load_shared(directory: Path = SCHEMES_DIR) -> SharedRules:
    return SharedRules.model_validate(_read(directory / "_shared.yaml"))
