"""Scheme-result reasons in the family's language, from data/templates/reasons/{en,hi,mr}.yaml.

The rules engine decides; this only words its results. Each rule result carries a `code` (e.g. 'age_min.fail')
and `params`; a scheme's reasons are the rule results that explain its outcome (as in rules/engine.py), plus the
member's problems that block it. Amounts are written the Indian way: ₹2,04,000.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from rules.engine import RuleResult, SchemeResult

REASONS_DIR = Path(__file__).resolve().parents[2] / "data" / "templates" / "reasons"
MONEY = {"income", "limit", "low", "high"}
# Which rule outcomes explain a scheme outcome (the same choice rules/engine.py makes).
EXPLAINS = {"not_eligible": ("fail",), "blocked_by_issues": ("blocked",), "check_at_office": ("check_at_office",),
            "eligible_on_documents": ("pass",)}


class ReasonTemplates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str
    words: dict[str, str]
    missing: dict[str, str]
    reasons: dict[str, str]
    issues: dict[str, str]
    confirm: str
    catalog: dict[str, str]  # scheme catalog lines (agents/catalog.py)


@lru_cache
def load_reasons(language: str) -> ReasonTemplates:
    t = ReasonTemplates.model_validate(yaml.safe_load((REASONS_DIR / f"{language}.yaml").read_text(encoding="utf-8")))
    if t.language != language:
        raise ValueError(f"{language}.yaml says language {t.language!r}")
    return t


def inr(amount: int | float) -> str:
    """₹ with Indian digit grouping: 204000 -> ₹2,04,000; 21000 -> ₹21,000."""
    digits = str(int(round(amount)))
    if len(digits) <= 3:
        return f"₹{digits}"
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join([head, *groups, tail] if head else [*groups, tail])


def _name(item: dict[str, Any], language: str) -> str:
    name = item.get("name_mr") if language != "en" else item.get("name_en")
    return name or item.get("name_en") or item.get("name_mr") or item.get("member_id", "")


def rule_reason(result: RuleResult, language: str) -> str:
    t = load_reasons(language)
    template = t.reasons.get(result.code)
    if template is None:
        return result.reason  # a code without wording yet: the engine's English trace
    params: dict[str, Any] = {}
    for key, value in result.params.items():
        if key in MONEY and isinstance(value, (int, float)):
            params[key] = inr(value)
        elif key in ("gender", "needs", "card", "source") and isinstance(value, str):
            params[key] = t.words.get(value, value)
        elif key == "items":
            params[key] = ", ".join(t.missing[i["kind"]].format(name=_name(i, language)) for i in value)
        else:
            params[key] = value
    return template.format(**params)


def scheme_reasons(result: SchemeResult, language: str) -> dict[str, list[str]]:
    """{'reasons': why this outcome, 'warnings': what to check} in the family's language."""
    t = load_reasons(language)
    explains = EXPLAINS.get(result.outcome, ())
    reasons = [rule_reason(r, language) for r in result.rules if r.outcome in explains]
    if result.outcome == "blocked_by_issues":
        blocking = {i.type for i in result.blocking_issues if i.member_id == result.member_id}
        reasons += [t.issues[k] for k in sorted(blocking) if k in t.issues]
    warnings = [rule_reason(r, language) for r in result.rules if r.outcome == "warning"]
    warnings += [t.confirm] if result.to_confirm else []
    return {"reasons": list(dict.fromkeys(reasons)), "warnings": list(dict.fromkeys(warnings))}
