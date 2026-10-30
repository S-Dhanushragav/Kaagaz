"""Scheme reasons in en/hi/mr: every engine code has wording, amounts in Indian format, outcome reasons chosen
like the engine, and no English engine strings in Hindi or Marathi."""

import re
from pathlib import Path

import pytest

from agents.reasons import inr, load_reasons, rule_reason, scheme_reasons
from agents.speech import speech_text
from agents.voice import LANGUAGES
from rules.engine import evaluate
from tests.test_rules import WOMAN, _issue, household

ENGINE = Path(__file__).resolve().parents[1] / "rules" / "engine.py"
CHECK_OUTCOMES = {  # codes made as '<check>.<outcome>' (the default)
    "gender": ("pass", "fail"), "age_min": ("pass", "fail"), "age_max": ("pass", "fail"),
    "age_below": ("pass", "fail"), "income_max": ("pass", "fail"),
    "income_bands": ("pass", "fail", "check_at_office"),
    "caste_household": ("pass", "blocked", "needs_other_proof"),
    "caste_applicant": ("check_at_office", "blocked", "pass", "fail"), "documents": ("pass",),
}


def _codes() -> set[str]:
    explicit = set(re.findall(r'code="([a-z_.]+)"', ENGINE.read_text(encoding="utf-8")))
    return explicit | {f"{c}.{o}" for c, outs in CHECK_OUTCOMES.items() for o in outs}


@pytest.mark.parametrize("n, text", [(0, "₹0"), (2, "₹2"), (999, "₹999"), (21000, "₹21,000"), (100000, "₹1,00,000"),
                                     (204000, "₹2,04,000"), (250001, "₹2,50,001"), (12345678, "₹1,23,45,678")])
def test_indian_amounts(n: int, text: str) -> None:
    assert inr(n) == text


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_engine_code_has_wording(language: str) -> None:
    t = load_reasons(language)
    assert len(_codes()) >= 30
    missing = _codes() - set(t.reasons)
    assert not missing, missing
    assert {"name_mismatch", "dob_mismatch", "not_on_ration_card", "missing_document", "unreadable"} <= set(t.issues)


@pytest.mark.parametrize("language", ["hi", "mr"])
def test_reasons_on_real_households_have_no_english(language: str) -> None:
    hh = household([WOMAN, {"id": "b", "gender": "M", "age": 70}], income=204000, castes={"a": "SC"})
    for r in evaluate(hh):
        shown = scheme_reasons(r, language)
        for text in shown["reasons"] + shown["warnings"]:
            assert not re.search(r"[A-Za-z]{3,}", text.replace("SC", "").replace("ST", "").replace("NB", "")), text


def test_income_and_age_reasons_in_english() -> None:
    hh = household([WOMAN], income=204000)
    ladki = next(r for r in evaluate(hh) if r.scheme_id == "ladki_bahin")
    reasons = scheme_reasons(ladki, "en")["reasons"]
    assert "Family income ₹2,04,000 is within the limit of ₹2,50,000." in reasons
    assert any(r.startswith("Age ") for r in reasons)
    income_rule = next(r for r in ladki.rules if r.code == "income_max.pass")
    assert rule_reason(income_rule, "mr") == "कुटुंबाचे उत्पन्न ₹2,04,000 आहे, ₹2,50,000 च्या मर्यादेत आहे."


def test_blocked_reasons_name_the_problem_and_missing_documents() -> None:
    hh = household([WOMAN], issues=[_issue("dob_mismatch", "a", ["id_a", "cc_a"])])
    r = next(x for x in evaluate(hh) if x.scheme_id == "ladki_bahin")
    reasons = scheme_reasons(r, "en")["reasons"]
    assert "The date of birth differs between documents." in reasons
    assert "The date of birth differs between documents: fix this first." in reasons
    no_card = household([WOMAN], castes={"a": "SC"}, ration_card=False)
    ujjwala = next(x for x in evaluate(no_card) if x.scheme_id == "pm_ujjwala")
    assert any(t.startswith("Missing: ration card") for t in scheme_reasons(ujjwala, "en")["reasons"])


def test_rupees_are_spoken_in_english() -> None:
    assert speech_text("Fee: about ₹75.", "en") == "Fee: about seventy-five rupees."
    assert speech_text("Income ₹2,04,000.", "en").startswith("Income ")


def test_age_limits_are_years_not_rupees() -> None:
    hh = household([{**WOMAN, "age": 48}], income=204000)
    shravanbal = next(r for r in evaluate(hh) if r.scheme_id == "shravanbal")
    reasons = scheme_reasons(shravanbal, "en")["reasons"]
    assert "Age 48 is under the minimum age of 65." in reasons
