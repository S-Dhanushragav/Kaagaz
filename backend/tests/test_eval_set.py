"""Generator v2 (EV001-EV030): quotas and rules; and v1 (HH001-HH010) stays byte-for-byte the same."""

import json
from collections import Counter
from pathlib import Path

import pytest

from schemas.documents import FIELD_MODELS
from synthetic import names_eval as E
from synthetic.generate import build_household
from synthetic.generate_eval import build_eval_set, schedule

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def eval_set():
    return build_eval_set()


@pytest.mark.parametrize("i", range(1, 11))
def test_v1_households_unchanged(i: int) -> None:
    """The sweep videos depend on HH001-HH010: regenerating them must give the committed ground truth."""
    committed = json.loads((ROOT / "synthetic" / "households" / f"HH{i:03d}" / "ground_truth.json").read_text(encoding="utf-8"))
    for d in committed["documents"]:  # written when rendering, not part of generation
        d.pop("files"), d.pop("photo")
    fresh = json.loads(build_household(42, i).model_dump_json())
    for d in fresh["documents"]:
        d.pop("files"), d.pop("photo")
    assert fresh == committed


def test_v2_is_deterministic(eval_set) -> None:
    again = build_eval_set()
    assert [h.model_dump_json() for h in again] == [h.model_dump_json() for h in eval_set]


def test_v2_quotas(eval_set) -> None:
    assert len(eval_set) == 30
    errors = Counter(e.type for h in eval_set for e in h.planted_errors)
    assert all(errors[t] >= 4 for t in ("name_mismatch", "dob_mismatch", "expired", "missing_document", "not_on_ration_card"))
    assert sum(not h.planted_errors for h in eval_set) >= 4  # clean households, for false alarms
    assert sum(len(h.members) >= 5 for h in eval_set) >= 8
    ages = Counter(m.age for h in eval_set for m in h.members)
    assert all(ages[a] >= 1 for a in (18, 21, 64, 65))
    incomes = {d.fields["annual_income"] for h in eval_set for d in h.documents if d.type == "income_certificate"}
    assert {21000, 100000, 150000, 250000} <= incomes and any(i < 21000 for i in incomes)
    assert Counter(h.documents[0].fields["card_colour"] for h in eval_set) == {"yellow": 10, "orange": 10, "white": 10}
    categories = {d.fields["category_en"] for h in eval_set for d in h.documents if d.type == "caste_certificate"}
    assert E.NEO_BUDDHIST.en in categories


def test_low_income_households_have_pension_age_members(eval_set) -> None:
    low = [h for h in eval_set if any(d.type == "income_certificate" and d.fields["annual_income"] <= 21000
                                      for d in h.documents)]
    assert any(any(m.age >= 65 for m in h.members) for h in low)
    assert any(any(m.age < 65 for m in h.members) for h in low)


def test_no_child_gets_father_name(eval_set) -> None:
    for h in eval_set:
        for m in h.members:
            if m.relation.en in ("Son", "Daughter"):
                assert m.given.en != m.middle.en, (h.id, m.full_name.en)


def test_missing_documents_are_adult_identity_cards_or_income(eval_set) -> None:
    for h in eval_set:
        members = {m.id: m for m in h.members}
        for e in h.planted_errors:
            if e.type == "missing_document":
                assert e.expected == "income_certificate" or (e.expected == "identity_card" and members[e.member_id].age >= 18)


def test_v2_ground_truth_validates_and_colour_matches_category(eval_set) -> None:
    for h in eval_set:
        for d in h.documents:
            FIELD_MODELS[d.type].model_validate(d.fields)
        card = h.documents[0].fields
        assert card["category_en"] == E.CARD_COLOURS[card["card_colour"]]["category"].en


def test_schedule_has_no_randomness() -> None:
    assert schedule() == schedule()


def test_rare_names_are_used(eval_set) -> None:
    rare = {p.en for p in E.RARE_MALE_NAMES + E.RARE_FEMALE_NAMES + E.RARE_SURNAMES}
    used = {part.en for h in eval_set for m in h.members for part in (m.given, m.surname)}
    assert len(rare & used) >= 10
