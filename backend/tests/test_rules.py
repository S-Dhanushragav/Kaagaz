"""Rules engine on hand-written households: every boundary, interpretation, and outcome order.

These are unit tests, not an eval: the expected outcomes are written by hand from the rules the
developer provided (data/schemes/*.yaml), so they check the engine, not the rules against themselves.
"""

from datetime import date

import pytest

from rules.engine import category_code, evaluate, financial_year_start
from rules.loader import load_schemes, load_shared
from schemas.documents import FIELD_MODELS, DocumentExtraction
from schemas.household import Household, HouseholdMember
from schemas.issues import Issue

REF = date(2026, 10, 27)
CATEGORY = {"SC": "Scheduled Caste (SC)", "ST": "Scheduled Tribe (ST)", "NB": "Neo-Buddhist",
            "OBC": "Other Backward Class (OBC)", "VJNT": "Vimukta Jati and Nomadic Tribes (VJNT)"}


def _doc(doc_id: str, doc_type: str, **fields) -> DocumentExtraction:
    model = FIELD_MODELS[doc_type]
    full = {k: None for k in model.model_fields} | ({"members": []} if doc_type == "ration_card" else {}) | fields
    return DocumentExtraction(document_id=doc_id, doc_type=doc_type, fields=model.model_validate(full))


def household(
    members: list[dict],
    *,
    income: int | None = 50000,
    income_issued: str = "01/10/2026",
    colour: str | None = "white",
    castes: dict[str, str] | None = None,
    issues: list[Issue] | None = None,
    ration_card: bool = True,
) -> Household:
    """members: dicts with id, gender, age, and optional no_id=True (identity card missing)."""
    docs: dict[str, DocumentExtraction] = {}
    hm = []
    for m in members:
        linked: dict[str, list[str]] = {}
        if not m.get("no_id"):
            docs[f"id_{m['id']}"] = _doc(f"id_{m['id']}", "identity_card", name_en=m["id"])
            linked["identity_card"] = [f"id_{m['id']}"]
        if castes and m["id"] in castes:
            docs[f"cc_{m['id']}"] = _doc(f"cc_{m['id']}", "caste_certificate", category_en=CATEGORY[castes[m["id"]]])
            linked["caste_certificate"] = [f"cc_{m['id']}"]
        hm.append(HouseholdMember(member_id=m["id"], on_ration_card=True, gender=m.get("gender"), age=m.get("age"),
                                  age_source="identity_card", documents=linked))
    if income is not None:
        docs["inc"] = _doc("inc", "income_certificate", annual_income=income, issue_date=income_issued)
    if ration_card:
        docs["rc"] = _doc("rc", "ration_card", card_colour=colour)
    return Household(reference_date=REF, ration_card_id="rc" if ration_card else None,
                     card_colour=colour if ration_card else None, members=hm, documents=docs,
                     income_document_id="inc" if income is not None else None, issues=issues or [])


def outcome(hh: Household, scheme: str, member: str = "a") -> str:
    return result(hh, scheme, member).outcome


def result(hh: Household, scheme: str, member: str = "a"):
    return next(r for r in evaluate(hh) if r.scheme_id == scheme and r.member_id == member)


WOMAN = {"id": "a", "gender": "F", "age": 30}


# ---------- loader: the YAML holds exactly the developer's values ----------

def test_scheme_files_load_with_status_source_and_date() -> None:
    schemes = {s.id: s for s in load_schemes()}
    assert set(schemes) == {"pm_ujjwala", "ladki_bahin", "sanjay_gandhi_niradhar", "shravanbal", "ramai_awas"}
    for s in schemes.values():
        for r in s.rules + s.needs_other_proof:
            assert r.status in ("verified", "conflict", "unverified") and r.source
            assert r.last_checked == date(2026, 10, 29)
    assert load_shared().rule("income_certificate_validity").status == "unverified"


def test_rule_values_match_the_provided_values() -> None:
    v = {(s.id, r.id): r.value for s in load_schemes() for r in s.rules}
    assert v["pm_ujjwala", "applicant_gender"] == "female" and v["pm_ujjwala", "applicant_min_age"] == 18
    assert v["pm_ujjwala", "household_category"]["qualifying"] == ["SC", "ST"]
    assert v["ladki_bahin", "applicant_min_age"] == 21 and v["ladki_bahin", "applicant_max_age"] == 65
    assert v["ladki_bahin", "family_income"] == 250000
    assert v["ladki_bahin", "income_certificate"]["not_required_for_cards"] == ["yellow", "orange"]
    assert v["sanjay_gandhi_niradhar", "applicant_age_below"] == 65
    assert v["sanjay_gandhi_niradhar", "family_income"] == 21000
    assert v["shravanbal", "applicant_min_age"] == 65 and v["shravanbal", "family_income"] == 21000
    assert v["ramai_awas", "applicant_category"]["qualifying"] == ["SC", "NB"]
    assert v["ramai_awas", "family_income"] == {"pass_max": 100000, "fail_above": 150000}
    ramai = next(s for s in load_schemes() if s.id == "ramai_awas")
    income_rule = next(r for r in ramai.rules if r.id == "family_income")
    assert income_rule.status == "conflict" and [x.value for x in income_rule.reported] == [100000, 120000, 150000]


def test_interpretations_recorded_for_decided_rules() -> None:
    rules = {(s.id, r.id): r for s in load_schemes() for r in s.rules}
    for key in [("ladki_bahin", "income_certificate"), ("pm_ujjwala", "household_category"),
                ("ramai_awas", "applicant_category")]:
        assert "Our reading" in rules[key].interpretation
    assert "Our reading" in load_shared().rule("income_certificate_validity").interpretation


# ---------- PM Ujjwala ----------

@pytest.mark.parametrize("age,expected", [(17, "not_eligible"), (18, "eligible_on_documents"), (19, "eligible_on_documents")])
def test_ujjwala_age_boundary(age: int, expected: str) -> None:
    assert outcome(household([{"id": "a", "gender": "F", "age": age}], castes={"a": "SC"}), "pm_ujjwala") == expected


def test_ujjwala_gender() -> None:
    assert outcome(household([{"id": "a", "gender": "M", "age": 40}], castes={"a": "SC"}), "pm_ujjwala") == "not_eligible"


def test_ujjwala_any_member_sc_or_st_qualifies_household() -> None:
    hh = household([WOMAN, {"id": "b", "gender": "M", "age": 40}], castes={"b": "ST"})
    r = result(hh, "pm_ujjwala")
    assert r.outcome == "eligible_on_documents"
    assert next(x for x in r.rules if x.rule_id == "household_category").outcome == "pass"


def test_ujjwala_without_sc_st_needs_other_proof_not_rejection() -> None:
    r = result(household([WOMAN], castes={"a": "OBC"}), "pm_ujjwala")
    assert r.outcome == "eligible_on_documents"
    assert "household_category" in [p.id for p in r.needs_other_proof]
    assert "no_lpg_connection" in [p.id for p in r.needs_other_proof]


def test_ujjwala_needs_identity_card_of_every_adult_only() -> None:
    adult_missing = household([WOMAN, {"id": "b", "gender": "M", "age": 18, "no_id": True}], castes={"a": "SC"})
    assert outcome(adult_missing, "pm_ujjwala") == "blocked_by_issues"
    child_missing = household([WOMAN, {"id": "c", "gender": "M", "age": 17, "no_id": True}], castes={"a": "SC"})
    assert outcome(child_missing, "pm_ujjwala") == "eligible_on_documents"
    assert outcome(household([WOMAN], castes={"a": "SC"}, ration_card=False), "pm_ujjwala") == "blocked_by_issues"


# ---------- Ladki Bahin ----------

@pytest.mark.parametrize("age,expected", [(20, "not_eligible"), (21, "eligible_on_documents"),
                                          (65, "eligible_on_documents"), (66, "not_eligible")])
def test_ladki_age_boundaries(age: int, expected: str) -> None:
    assert outcome(household([{"id": "a", "gender": "F", "age": age}]), "ladki_bahin") == expected


@pytest.mark.parametrize("income,expected", [(250000, "eligible_on_documents"), (250001, "not_eligible")])
def test_ladki_income_boundary(income: int, expected: str) -> None:
    assert outcome(household([WOMAN], income=income), "ladki_bahin") == expected


@pytest.mark.parametrize("colour,expected", [("yellow", "eligible_on_documents"), ("orange", "eligible_on_documents"),
                                             ("white", "blocked_by_issues")])
def test_ladki_card_colour_without_income_certificate(colour: str, expected: str) -> None:
    r = result(household([WOMAN], income=None, colour=colour), "ladki_bahin")
    assert r.outcome == expected
    if expected == "eligible_on_documents":
        assert any("our reading" in x.reason for x in r.rules)


def test_ladki_no_ration_card_and_no_income_certificate_is_blocked() -> None:
    assert outcome(household([WOMAN], income=None, ration_card=False), "ladki_bahin") == "blocked_by_issues"


def test_ladki_certificate_above_limit_fails_even_with_yellow_card() -> None:
    assert outcome(household([WOMAN], income=300000, colour="yellow"), "ladki_bahin") == "not_eligible"


def test_ladki_male_not_eligible() -> None:
    assert outcome(household([{"id": "a", "gender": "M", "age": 30}]), "ladki_bahin") == "not_eligible"


# ---------- pensions ----------

@pytest.mark.parametrize("age,expected", [(64, "eligible_on_documents"), (65, "not_eligible")])
def test_sanjay_gandhi_age_below_65(age: int, expected: str) -> None:
    assert outcome(household([{"id": "a", "gender": "M", "age": age}], income=12000), "sanjay_gandhi_niradhar") == expected


@pytest.mark.parametrize("age,expected", [(64, "not_eligible"), (65, "eligible_on_documents")])
def test_shravanbal_age_65_and_over(age: int, expected: str) -> None:
    assert outcome(household([{"id": "a", "gender": "F", "age": age}], income=12000), "shravanbal") == expected


@pytest.mark.parametrize("scheme,age", [("sanjay_gandhi_niradhar", 40), ("shravanbal", 70)])
@pytest.mark.parametrize("income,expected", [(21000, "eligible_on_documents"), (21001, "not_eligible")])
def test_pension_income_boundary(scheme: str, age: int, income: int, expected: str) -> None:
    assert outcome(household([{"id": "a", "gender": "F", "age": age}], income=income), scheme) == expected


def test_pension_without_income_certificate_is_blocked_even_with_yellow_card() -> None:
    hh = household([{"id": "a", "gender": "F", "age": 70}], income=None, colour="yellow")
    assert outcome(hh, "shravanbal") == "blocked_by_issues"  # the card exemption is Ladki Bahin's only


def test_sanjay_gandhi_lists_covered_group_as_other_proof() -> None:
    r = result(household([{"id": "a", "gender": "F", "age": 40}], income=12000), "sanjay_gandhi_niradhar")
    assert [p.id for p in r.needs_other_proof] == ["covered_group"]


# ---------- Ramai Awas ----------

@pytest.mark.parametrize("income,expected", [(100000, "eligible_on_documents"), (100001, "check_at_office"),
                                             (150000, "check_at_office"), (150001, "not_eligible")])
def test_ramai_income_bands(income: int, expected: str) -> None:
    r = result(household([WOMAN], income=income, castes={"a": "SC"}), "ramai_awas")
    assert r.outcome == expected
    band = next(x for x in r.rules if x.rule_id == "family_income")
    assert band.status == "conflict"


def test_ramai_neo_buddhist_passes() -> None:
    assert outcome(household([WOMAN], castes={"a": "NB"}), "ramai_awas") == "eligible_on_documents"


def test_ramai_other_members_certificate_is_check_at_office() -> None:
    hh = household([WOMAN, {"id": "b", "gender": "M", "age": 45}], castes={"b": "SC"})
    assert outcome(hh, "ramai_awas", "a") == "check_at_office"
    assert outcome(hh, "ramai_awas", "b") == "eligible_on_documents"


def test_ramai_other_category_fails_and_no_certificate_blocks() -> None:
    assert outcome(household([WOMAN], castes={"a": "OBC"}), "ramai_awas") == "not_eligible"
    assert outcome(household([WOMAN]), "ramai_awas") == "blocked_by_issues"
    assert outcome(household([WOMAN], income=None, castes={"a": "SC"}), "ramai_awas") == "blocked_by_issues"


# ---------- issues and outcome order ----------

def _issue(kind: str, member: str | None, docs: list[str], severity: str = "blocker", **evidence) -> Issue:
    return Issue(type=kind, severity=severity, member_id=member, documents=docs, evidence=evidence, message=kind)


def test_dob_mismatch_blocks_age_rules() -> None:
    hh = household([WOMAN], issues=[_issue("dob_mismatch", "a", ["id_a", "cc_a"])])
    r = result(hh, "ladki_bahin")
    assert r.outcome == "blocked_by_issues" and r.blocking_issues[0].type == "dob_mismatch"


def test_definite_failure_beats_blocker() -> None:
    hh = household([{"id": "a", "gender": "M", "age": 30}], issues=[_issue("dob_mismatch", "a", ["id_a"])])
    assert outcome(hh, "ladki_bahin") == "not_eligible"  # a man: no fix makes him eligible


def test_member_blockers_block_every_scheme() -> None:
    hh = household([WOMAN], castes={"a": "SC"}, issues=[_issue("name_mismatch", "a", ["id_a", "rc"])])
    for scheme in ("pm_ujjwala", "ladki_bahin", "ramai_awas"):
        assert outcome(hh, scheme) == "blocked_by_issues"


def test_name_to_confirm_never_blocks_but_is_listed() -> None:
    confirm = _issue("name_mismatch", "a", ["id_a", "rc"], severity="confirm")
    plain = household([WOMAN], castes={"a": "SC"})
    hh = household([WOMAN], castes={"a": "SC"}, issues=[confirm])
    for scheme in ("pm_ujjwala", "ladki_bahin", "ramai_awas"):
        r = result(hh, scheme)
        assert r.outcome == outcome(plain, scheme) and r.outcome != "blocked_by_issues"
        assert r.to_confirm == [confirm] and confirm.message in r.warnings and not r.blocking_issues


def test_unreadable_income_blocks_income_rules() -> None:
    hh = household([WOMAN], income=None)
    hh.documents["inc"] = _doc("inc", "income_certificate", annual_income=None, issue_date="01/10/2026")
    hh.income_document_id = "inc"
    assert outcome(hh, "ladki_bahin") == "blocked_by_issues"


def test_issue_on_income_certificate_blocks_income_rules_for_everyone() -> None:
    hh = household([WOMAN, {"id": "b", "gender": "M", "age": 70}], income=12000,
                   issues=[_issue("name_mismatch", "b", ["inc", "rc"])])
    r = result(hh, "ladki_bahin", "a")
    assert r.outcome == "blocked_by_issues" and r.blocking_issues[0].documents == ["inc", "rc"]


def test_unknown_age_is_blocked_not_rejected() -> None:
    assert outcome(household([{"id": "a", "gender": "F", "age": None}]), "ladki_bahin") == "blocked_by_issues"


def test_unknown_gender_is_blocked() -> None:
    assert outcome(household([{"id": "a", "gender": None, "age": 30}]), "ladki_bahin") == "blocked_by_issues"


# ---------- income certificate validity (warning only) ----------

def test_financial_year_start() -> None:
    assert financial_year_start(date(2026, 10, 27)) == date(2026, 4, 1)
    assert financial_year_start(date(2026, 3, 31)) == date(2025, 4, 1)
    assert financial_year_start(date(2026, 4, 1)) == date(2026, 4, 1)


@pytest.mark.parametrize("issued,warned", [("31/03/2026", True), ("01/04/2026", False)])
def test_old_income_certificate_warns_but_never_blocks(issued: str, warned: bool) -> None:
    r = result(household([WOMAN], income_issued=issued), "ladki_bahin")
    assert r.outcome == "eligible_on_documents"
    assert bool(r.warnings) == warned
    if warned:
        assert "may need renewal, check at the office" in r.warnings[0]


def test_results_carry_rule_values_status_and_source() -> None:
    r = result(household([WOMAN]), "ladki_bahin")
    by_id = {x.rule_id: x for x in r.rules}
    assert by_id["applicant_min_age"].value == 21 and by_id["applicant_min_age"].status == "verified"
    assert by_id["applicant_min_age"].source_url == "https://myscheme.gov.in/schemes/mmlby"


def test_category_codes() -> None:
    for code, text in CATEGORY.items():
        assert category_code(_doc("c", "caste_certificate", category_en=text)) == code
    assert category_code(_doc("c", "caste_certificate", category_mr="नवबौद्ध")) == "NB"
