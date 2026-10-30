"""Re-check comparison: problems fixed / still open / new, matched by type, member name (case and spacing
ignored) and document type; scheme outcomes that changed for the same person."""

from app.casefile import compare
from storage.models import CheckData, StoredMember, StoredOutcome, StoredProblem


def _member(mid: str, en: str) -> StoredMember:
    return StoredMember(member_id=mid, name_mr=None, name_en=en, relation_en=None, age=40, on_ration_card=True)


def _problem(kind: str, who: str | None, *docs: str) -> StoredProblem:
    return StoredProblem(type=kind, member_id=None, member_name=who, member_name_mr=None, document_types=list(docs),
                         waiting=False)


def _outcome(mid: str, scheme: str, outcome: str) -> StoredOutcome:
    return StoredOutcome(member_id=mid, scheme_id=scheme, outcome=outcome, reasons=[], warnings=[])


def _data(members, problems, outcomes) -> CheckData:
    return CheckData(members=members, documents=[], problems=problems, outcomes=outcomes, steps=[], answers=[])


def test_problems_fixed_still_open_and_new() -> None:
    before = _data([_member("r1", "Savita Aditya Bhosale")], [
        _problem("name_mismatch", "Savita Aditya Bhosale", "identity_card", "ration_card"),
        _problem("expired", "Aditya Yogesh Bhosale", "income_certificate"),
        _problem("dob_mismatch", "Lata Aditya Bhosale", "identity_card", "caste_certificate"),
    ], [])
    after = _data([_member("r1", "Savita Aditya Bhosale")], [
        _problem("expired", "aditya  yogesh BHOSALE", "income_certificate"),  # same person, other spacing/case
        _problem("dob_mismatch", "Lata Aditya Bhosale", "identity_card"),  # overlapping document types
        _problem("missing_document", "Lata Aditya Bhosale", "caste_certificate"),
    ], [])
    c = compare(before, after)
    assert [p["type"] for p in c["fixed"]] == ["name_mismatch"]
    assert [p["type"] for p in c["still_open"]] == ["expired", "dob_mismatch"]
    assert [p["type"] for p in c["new"]] == ["missing_document"]


def test_same_type_for_another_person_or_document_is_not_the_same_problem() -> None:
    before = _data([], [_problem("name_mismatch", "Savita", "identity_card")], [])
    after = _data([], [_problem("name_mismatch", "Lata", "identity_card"),
                       _problem("name_mismatch", "Savita", "caste_certificate")], [])
    c = compare(before, after)
    assert len(c["fixed"]) == 1 and len(c["new"]) == 2 and c["still_open"] == []


def test_scheme_outcomes_that_changed() -> None:
    before = _data([_member("r1", "Savita"), _member("r2", "Lata")],
                   [], [_outcome("r1", "ladki_bahin", "blocked_by_issues"), _outcome("r2", "ladki_bahin", "not_eligible")])
    after = _data([_member("m7", "SAVITA"), _member("r2", "Lata")],  # member ids can differ between checks
                  [], [_outcome("m7", "ladki_bahin", "eligible_on_documents"), _outcome("r2", "ladki_bahin", "not_eligible")])
    (change,) = compare(before, after)["outcomes_changed"]
    assert change == {"member_name": "SAVITA", "member_name_mr": None, "scheme_id": "ladki_bahin",
                      "before": "blocked_by_issues", "after": "eligible_on_documents"}
