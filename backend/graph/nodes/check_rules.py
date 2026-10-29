"""check_rules node: deterministic scheme rules for every member (rules/engine.py). No LLM calls."""

from rules.engine import SchemeResult, evaluate
from schemas.household import Household


def check_rules(household: Household) -> list[SchemeResult]:
    return evaluate(household)
