"""Household builder: linking, separate spelling checks, duplicates, missing documents, unreadable fields."""

import json
from datetime import date
from pathlib import Path

import pytest

from clients.llm import LLMResponse, TokenUsage
from graph.nodes.build_household import Adjudication, NameQuery, NameRead, build_household, llm_name_verifier
from schemas.documents import FIELD_MODELS, DocumentExtraction
from synthetic.truth import extractions_from_truth, match_issues

REF = date(2026, 10, 27)
EVAL = Path(__file__).resolve().parents[2] / "synthetic" / "eval_households"


def _gts() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(EVAL.glob("EV*/ground_truth.json"))]


def _no_llm(a, b):
    raise AssertionError("adjudicator should not be needed")


def _doc(doc_id: str, doc_type: str, **fields) -> DocumentExtraction:
    model = FIELD_MODELS[doc_type]
    full = {k: None for k in model.model_fields} | ({"members": []} if doc_type == "ration_card" else {}) | fields
    return DocumentExtraction(document_id=doc_id, doc_type=doc_type, fields=model.model_validate(full))


def _row(mr: str, en: str, gender: str, age: int, relation: str = "Son") -> dict:
    return {"name_mr": mr, "name_en": en, "relation_mr": "र", "relation_en": relation,
            "gender_mr": "पुरुष" if gender == "M" else "स्त्री", "gender_en": "Male" if gender == "M" else "Female",
            "age": age}


def _card(*rows: dict, colour: str = "white") -> DocumentExtraction:
    return _doc("rc", "ration_card", card_colour=colour, members=list(rows))


def _id(doc_id: str, mr: str | None, en: str | None, dob: str | None, gender: str = "M", last4: str = "1234") -> DocumentExtraction:
    return _doc(doc_id, "identity_card", name_mr=mr, name_en=en, dob=dob, gender_en="Male" if gender == "M" else "Female",
                gender_mr="पुरुष" if gender == "M" else "स्त्री", id_number=f"XXXX XXXX {last4}")


def _income(holder_en: str = "Sunil Ramesh Patil", issued: str = "01/10/2026") -> DocumentExtraction:
    return _doc("inc", "income_certificate", name_en=holder_en, annual_income=50000, issue_date=issued)


SUNIL = _row("सुनील रमेश पाटील", "Sunil Ramesh Patil", "M", 40, "Self")


def types(hh) -> list[str]:
    return sorted(i.type for i in hh.issues)


# ---------- on the evaluation set (ground truth = a perfect reader) ----------

def test_every_planted_error_found_without_false_alarms() -> None:
    gts = _gts()
    assert len(gts) == 30
    caught = 0
    for gt in gts:
        hh = build_household(extractions_from_truth(gt), date.fromisoformat(gt["reference_date"]), adjudicate=_no_llm)
        m = match_issues(gt, hh.issues)
        assert not m.missed, (gt["id"], m.missed)
        assert not m.false_alarms, (gt["id"], [(i.type, i.documents) for i in m.false_alarms])
        caught += len(m.caught)
    assert caught == sum(len(gt["planted_errors"]) for gt in gts)


def test_clean_household_has_no_issues() -> None:
    gt = next(g for g in _gts() if not g["planted_errors"])
    hh = build_household(extractions_from_truth(gt), REF, adjudicate=_no_llm)
    assert [i for i in hh.issues if i.severity != "info"] == []
    assert all(m.on_ration_card for m in hh.members)


# ---------- linking and the separate spelling check ----------

def test_spelling_difference_is_a_mismatch_even_when_linked() -> None:
    hh = build_household([_card(SUNIL), _id("id1", "सुनिल रमेश पाटील", "Suneel Ramesh Patil", "01/01/1986"), _income()], REF,
                         adjudicate=_no_llm)
    assert hh.member("r1").documents["identity_card"] == ["id1"]  # linked...
    mm = [i for i in hh.issues if i.type == "name_mismatch"]
    assert len(mm) == 1 and mm[0].member_id == "r1"  # ...and still reported
    assert mm[0].evidence["names"]["en"] == {"rc": "Sunil Ramesh Patil", "id1": "Suneel Ramesh Patil",
                                             "inc": "Sunil Ramesh Patil"}


def test_null_field_is_never_a_mismatch() -> None:
    hh = build_household([_card(SUNIL), _id("id1", None, "Sunil Ramesh Patil", None), _income()], REF, adjudicate=_no_llm)
    assert "name_mismatch" not in types(hh) and "dob_mismatch" not in types(hh)
    unreadable = [i for i in hh.issues if i.type == "unreadable" and i.documents == ["id1"]]
    assert unreadable and set(unreadable[0].evidence["fields"]) == {"name_mr", "dob"}
    assert hh.member("r1").age == 40 and hh.member("r1").age_source == "ration_card"  # fallback, and says so


def test_age_comes_from_identity_card() -> None:
    hh = build_household([_card(SUNIL), _id("id1", "सुनील रमेश पाटील", "Sunil Ramesh Patil", "27/10/1981"), _income()], REF,
                         adjudicate=_no_llm)
    assert hh.member("r1").age == 45 and hh.member("r1").age_source == "identity_card"


def test_document_of_someone_else_is_not_on_ration_card() -> None:
    hh = build_household([_card(SUNIL), _id("id1", "सुनील रमेश पाटील", "Sunil Ramesh Patil", "01/01/1986"),
                          _id("id2", "रेखा अनिल जाधव", "Rekha Anil Jadhav", "01/01/1990", "F", "9999"), _income()], REF,
                         adjudicate=_no_llm)
    nor = [i for i in hh.issues if i.type == "not_on_ration_card"]
    assert len(nor) == 1 and nor[0].documents == ["id2"] and nor[0].member_id == "x1"


def test_borderline_score_asks_the_model_and_logs_reason() -> None:
    asked = []

    def adjudicate(a, b):
        asked.append((a, b))
        return Adjudication(same_person=True, reason="same first name, spelling differs")

    card = _card(_row("सुनील रमेश पाटील", "Sunil Ramesh Patil", "M", 40, "Self"))
    doc = _id("id1", None, "Sunilkumar Ramesh Patil", "01/01/1986")  # scores in the 70-90 band
    hh = build_household([card, doc, _income()], REF, adjudicate=adjudicate)
    link = next(l for l in hh.links if l.document_id == "id1")
    assert 70 <= link.score < 90 and link.method == "llm" and "spelling differs" in link.reason
    assert asked and hh.llm_calls == 1 and hh.member("r1").documents["identity_card"] == ["id1"]


def test_model_saying_no_leaves_document_unlinked() -> None:
    card = _card(_row("सुनील रमेश पाटील", "Sunil Ramesh Patil", "M", 40, "Self"))
    hh = build_household([card, _id("id1", None, "Sunilkumar Ramesh Patil", "01/01/1986"), _income()], REF,
                         adjudicate=lambda a, b: Adjudication(same_person=False, reason="different person"))
    assert "not_on_ration_card" in types(hh)


def test_tie_between_members_broken_by_gender_and_age() -> None:
    card = _card(_row("अनिल सुनील पाटील", "Anil Sunil Patil", "M", 30), _row("अनिता सुनील पाटील", "Anita Sunil Patil", "F", 28))
    doc = _id("id1", None, "Ani Sunil Patil", "01/01/1998", "F")
    hh = build_household([card, doc, _income("Anil Sunil Patil")], REF,
                         adjudicate=lambda a, b: Adjudication(same_person=True, reason="ok"))
    link = next(l for l in hh.links if l.document_id == "id1")
    assert link.method in ("tiebreak", "llm") and link.member_id == "r2"


# ---------- duplicates, missing documents, expiry ----------

def test_duplicate_identity_cards_are_merged() -> None:
    a = _id("id1", "सुनील रमेश पाटील", "Sunil Ramesh Patil", "01/01/1986")
    b = _id("id1_again", "सुनील रमेश पाटील", None, "01/01/1986")
    hh = build_household([_card(SUNIL), a, b, _income()], REF, adjudicate=_no_llm)
    dup = [i for i in hh.issues if i.type == "duplicate_merged"]
    assert len(dup) == 1 and dup[0].severity == "info" and dup[0].evidence["kept"] == "id1"
    assert "id1_again" not in hh.documents and "not_on_ration_card" not in types(hh)


@pytest.mark.parametrize("age,severity", [(18, "blocker"), (17, "info")])
def test_missing_identity_card_adult_blocks_child_is_info(age: int, severity: str) -> None:
    child = _row("ओंकार सुनील पाटील", "Omkar Sunil Patil", "M", age)
    hh = build_household([_card(SUNIL, child), _id("id1", "सुनील रमेश पाटील", "Sunil Ramesh Patil", "01/01/1986"),
                          _income()], REF, adjudicate=_no_llm)
    missing = [i for i in hh.issues if i.type == "missing_document"]
    assert len(missing) == 1 and missing[0].member_id == "r2" and missing[0].severity == severity


def test_missing_income_certificate_and_ration_card() -> None:
    hh = build_household([_id("id1", "सुनील रमेश पाटील", "Sunil Ramesh Patil", "01/01/1986")], REF, adjudicate=_no_llm)
    missing = {i.evidence["document_type"] for i in hh.issues if i.type == "missing_document"}
    assert missing == {"ration_card", "income_certificate"}


@pytest.mark.parametrize("issued,expired", [("31/03/2026", True), ("01/04/2026", False)])
def test_old_income_certificate_is_a_warning(issued: str, expired: bool) -> None:
    hh = build_household([_card(SUNIL), _id("id1", "सुनील रमेश पाटील", "Sunil Ramesh Patil", "01/01/1986"),
                          _income(issued=issued)], REF, adjudicate=_no_llm)
    exp = [i for i in hh.issues if i.type == "expired"]
    assert bool(exp) == expired
    if expired:
        assert exp[0].severity == "warning" and exp[0].member_id == "r1"


def test_unreadable_document_points_to_recapture() -> None:
    bad = DocumentExtraction(document_id="blurry", unreadable=True, error="invalid after retry")
    hh = build_household([_card(SUNIL), bad, _income()], REF, adjudicate=_no_llm)
    un = [i for i in hh.issues if i.type == "unreadable"]
    assert un[0].documents == ["blurry"] and "photo" in un[0].message


# ---------- secondary linking (name score 50-70, age and gender fit one member) ----------

JADHAV = [_row("महेश विठ्ठल जाधव", "Mahesh Vitthal Jadhav", "M", 45, "Self"),
          _row("ज्ञानदा महेश जाधव", "Dnyanada Mahesh Jadhav", "F", 20, "Daughter")]
SHYANADA = ("शयनदा महेश जाधव", "Shyanada Mahesh Jadhav")  # a misread of the daughter's name


def test_secondary_link_asks_the_model_when_age_and_gender_fit_one_member() -> None:
    asked = []

    def adjudicate(a, b):
        asked.append(b["en"])
        return Adjudication(same_person=True, reason="same age and gender; first name a likely misread")

    hh = build_household([_card(*JADHAV), _id("id1", "महेश विठ्ठल जाधव", "Mahesh Vitthal Jadhav", "01/01/1981"),
                          _id("id2", *SHYANADA, "01/01/2006", "F", "5678"), _income("Mahesh Vitthal Jadhav")], REF,
                         adjudicate=adjudicate)
    link = next(l for l in hh.links if l.document_id == "id2")
    assert 50 <= link.score < 70 and link.method == "llm" and link.reason.startswith("secondary")
    assert asked == ["Dnyanada Mahesh Jadhav"] and hh.llm_calls == 1
    assert hh.member("r2").documents["identity_card"] == ["id2"] and "not_on_ration_card" not in types(hh)


def test_secondary_link_not_used_when_two_members_fit() -> None:
    twin = _row("ज्ञानेश्वरी महेश जाधव", "Dnyaneshwari Mahesh Jadhav", "F", 21, "Daughter")
    hh = build_household([_card(*JADHAV, twin), _id("id1", "महेश विठ्ठल जाधव", "Mahesh Vitthal Jadhav", "01/01/1981"),
                          _id("id2", *SHYANADA, "01/01/2006", "F", "5678"), _income("Mahesh Vitthal Jadhav")], REF,
                         adjudicate=_no_llm)
    assert "not_on_ration_card" in types(hh)


@pytest.mark.parametrize("dob, gender", [(None, "F"), ("01/01/2006", "M"), ("01/01/1996", "F")])
def test_secondary_link_needs_matching_age_and_gender(dob: str | None, gender: str) -> None:
    hh = build_household([_card(*JADHAV), _id("id1", "महेश विठ्ठल जाधव", "Mahesh Vitthal Jadhav", "01/01/1981"),
                          _id("id2", *SHYANADA, dob, gender, "5678"), _income("Mahesh Vitthal Jadhav")], REF,
                         adjudicate=_no_llm)
    assert "not_on_ration_card" in types(hh)


# ---------- name verification before a mismatch is reported ----------

SUNEEL_ID = _id("id1", "सुनिल रमेश पाटील", "Suneel Ramesh Patil", "01/01/1986")


def _verifier(reads: dict[str, NameRead], seen: list[NameQuery]):
    def verify(q: NameQuery) -> NameRead:
        seen.append(q)
        return reads[q.document_id]
    return verify


def test_mismatch_confirmed_by_re_read_is_reported_with_both_reads() -> None:
    seen: list[NameQuery] = []
    reads = {"rc": NameRead(name_mr="सुनील रमेश पाटील", name_en="Sunil Ramesh Patil"),
             "id1": NameRead(name_mr="सुनिल रमेश पाटील", name_en="Suneel Ramesh Patil"),
             "inc": NameRead(name_mr=None, name_en="Sunil Ramesh Patil")}
    hh = build_household([_card(SUNIL), SUNEEL_ID, _income()], REF, adjudicate=_no_llm, verify=_verifier(reads, seen))
    mm = [i for i in hh.issues if i.type == "name_mismatch"]
    assert len(mm) == 1 and "id1" in mm[0].documents
    assert mm[0].evidence["verification"]["id1"] == {"first_read": {"mr": "सुनिल रमेश पाटील", "en": "Suneel Ramesh Patil"},
                                                     "re_read": {"mr": "सुनिल रमेश पाटील", "en": "Suneel Ramesh Patil"}}
    assert hh.verification_calls == 3 == len(seen)
    assert next(q for q in seen if q.document_id == "rc").row == 1  # the member's row on the ration card
    assert next(q for q in seen if q.document_id == "id1").row is None


def test_mismatch_not_confirmed_by_re_read_stays_for_the_family_to_confirm() -> None:
    same = NameRead(name_mr="सुनील रमेश पाटील", name_en="Sunil Ramesh Patil")
    hh = build_household([_card(SUNIL), SUNEEL_ID, _income()], REF, adjudicate=_no_llm,
                         verify=_verifier({"rc": same, "id1": same, "inc": same}, []))
    mm = [i for i in hh.issues if i.type == "name_mismatch"]
    assert len(mm) == 1 and mm[0].severity == "confirm" and "id1" in mm[0].documents  # never dropped, never info
    assert mm[0].evidence["names"]["en"]["id1"] == "Suneel Ramesh Patil"  # both spellings, as first read
    assert mm[0].evidence["verification"]["id1"]["re_read"]["en"] == "Sunil Ramesh Patil"


def test_re_read_confirming_one_script_only() -> None:
    reads = {"rc": NameRead(name_mr="सुनील रमेश पाटील", name_en="Sunil Ramesh Patil"),
             "id1": NameRead(name_mr="सुनील रमेश पाटील", name_en="Suneel Ramesh Patil"),  # Marathi not confirmed
             "inc": NameRead(name_mr=None, name_en="Sunil Ramesh Patil")}
    hh = build_household([_card(SUNIL), SUNEEL_ID, _income()], REF, adjudicate=_no_llm, verify=_verifier(reads, []))
    by_severity = {i.severity: i for i in hh.issues if i.type == "name_mismatch"}
    assert set(by_severity) == {"blocker", "confirm"}
    assert set(by_severity["blocker"].evidence["names"]) == {"en"} and set(by_severity["confirm"].evidence["names"]) == {"mr"}


def test_failed_re_read_keeps_the_mismatch_as_blocker() -> None:
    failed = NameRead(error="verification call failed: timeout")
    hh = build_household([_card(SUNIL), SUNEEL_ID, _income()], REF, adjudicate=_no_llm,
                         verify=_verifier({"rc": failed, "id1": failed, "inc": failed}, []))
    mm = [i for i in hh.issues if i.type == "name_mismatch"]
    assert len(mm) == 1 and mm[0].severity == "blocker"
    assert mm[0].evidence["verification"]["id1"]["error"].startswith("verification call failed")


def test_secondary_link_re_reads_the_ration_card_row_first() -> None:
    """The card's row was misread (Shyanada); its re-read (Dnyanada) matches the identity card: linked, no model."""
    card = _card(JADHAV[0], _row(*SHYANADA, "F", 20, "Daughter"))
    seen: list[NameQuery] = []
    reads = {"rc": NameRead(name_mr="ज्ञानदा महेश जाधव", name_en="Dnyanada Mahesh Jadhav"),
             "id2": NameRead(name_mr="ज्ञानदा महेश जाधव", name_en="Dnyanada Mahesh Jadhav")}
    hh = build_household([card, _id("id1", "महेश विठ्ठल जाधव", "Mahesh Vitthal Jadhav", "01/01/1981"),
                          _id("id2", "ज्ञानदा महेश जाधव", "Dnyanada Mahesh Jadhav", "01/01/2006", "F", "5678"),
                          _income("Mahesh Vitthal Jadhav")], REF, adjudicate=_no_llm, verify=_verifier(reads, seen))
    link = next(l for l in hh.links if l.document_id == "id2")
    assert link.member_id == "r2" and link.score >= 90 and "re-read" in link.reason
    assert (seen[0].document_id, seen[0].row) == ("rc", 2)
    assert "not_on_ration_card" not in types(hh)
    # The first read still differs from the identity card; the re-read doesn't confirm it, so the family checks it.
    mm = [i for i in hh.issues if i.type == "name_mismatch"]
    assert [i.severity for i in mm] == ["confirm"]
    assert hh.verification_calls == 2  # the card row once (reused by the name check), the identity card once


def test_secondary_link_passes_the_re_read_name_to_the_model() -> None:
    asked = []

    def adjudicate(a, b):
        asked.append(b["en"])
        return Adjudication(same_person=False, reason="different first names")

    reads = {"rc": NameRead(name_mr=None, name_en="Shyamala Mahesh Jadhav")}  # still not a 90+ match
    hh = build_household([_card(*JADHAV), _id("id1", "महेश विठ्ठल जाधव", "Mahesh Vitthal Jadhav", "01/01/1981"),
                          _id("id2", *SHYANADA, "01/01/2006", "F", "5678"), _income("Mahesh Vitthal Jadhav")], REF,
                         adjudicate=adjudicate, verify=_verifier(reads, []))
    assert asked == ["Shyamala Mahesh Jadhav"] and "not_on_ration_card" in types(hh)


def test_llm_name_verifier_reads_one_row_at_medium_effort() -> None:
    calls = []

    def fake_llm(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return LLMResponse(text='{"name_mr": "ज्ञानदा महेश जाधव", "name_en": " Dnyanada Mahesh Jadhav "}',
                           task="vision", provider="meta", model="m", usage=TokenUsage(prompt_tokens=10, completion_tokens=5))

    verify = llm_name_verifier({"rc": [b"img"]}, overrides={"model": "m"}, llm=fake_llm)
    read = verify(NameQuery(document_id="rc", doc_type="ration_card", row=2, relation="Daughter"))
    assert read.name_en == "Dnyanada Mahesh Jadhav" and read.name_mr == "ज्ञानदा महेश जाधव" and read.usage.prompt_tokens == 10
    prompt, kwargs = calls[0]
    assert "member number 2" in prompt and "Daughter" in prompt and "letter by letter" in prompt
    assert kwargs["overrides"] == {"reasoning_effort": "medium", "model": "m"} and kwargs["task"] == "vision"
    assert verify(NameQuery(document_id="missing", doc_type="identity_card")).error == "no image for this document"
    assert len(calls) == 1
