"""Voice templates (data/templates/voice): coverage, exact offices, no internal ids, no promised time limits."""

import json
import re
import string
from datetime import date
from pathlib import Path

import pytest

from agents.fix_planner import finalize, planner_issues
from agents.tools import load_fixes
from agents.voice import LANGUAGES, OFFICE_REFERRALS, PLACEHOLDERS, load_voice, question_text, step_voice
from graph.nodes.build_household import build_household
from rules.engine import evaluate
from schemas.fixes import FixStep, PlannerIssue
from synthetic.truth import extractions_from_truth

FIXES = load_fixes()
EVAL = Path(__file__).resolve().parents[2] / "synthetic" / "eval_households"
DOC_TYPES = ("ration_card", "identity_card", "income_certificate", "caste_certificate")


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _all_templates(language: str) -> dict[str, str]:
    t = load_voice(language)
    return {**{f"procedures.{k}": v for k, v in t.procedures.items()}, "ask_at_office": t.ask_at_office,
            **{f"questions.{k}": v for k, v in t.questions.items()}, "law_sets": t.law_sets}


def _step(p_id: str) -> FixStep:
    p = FIXES[p_id]
    return FixStep(kind="fix", issue_ids=["i1"], member_id="r1", procedure_id=p_id,
                   office=p.office.value if p.office else None, bring=[f.value for f in p.bring],
                   fee=p.fee.value if p.fee else None, time_limit=p.time_limit.value if p.time_limit else None,
                   cautions=[f.value for f in p.cautions])


ISSUE = PlannerIssue(id="i1", type="name_mismatch", severity="blocker", member_id="r1", member_name="Sunil Ramesh Patil",
                     member_name_mr="सुनील रमेश पाटील", documents={"rc": "ration_card", "id_m1": "identity_card"},
                     values={"rc": "सुनील रमेश पाटील / Sunil Ramesh Patil", "id_m1": "सुनिल रमेश पाटील / Suneel Ramesh Patil"},
                     detail="")


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_procedure_question_and_document_has_a_template(language: str) -> None:
    t = load_voice(language)
    assert set(t.procedures) == set(FIXES)
    assert set(t.questions) == {"which_is_correct", "compare"} and t.ask_at_office
    assert set(t.documents) == set(DOC_TYPES) and set(t.options) == {"same", "different", "not sure"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_templates_use_only_allowed_placeholders_and_no_numbers(language: str) -> None:
    for name, template in _all_templates(language).items():
        assert _placeholders(template) <= PLACEHOLDERS, name
        assert not re.search(r"\d", template), f"{name}: numbers must come from the knowledge base"
    for p_id, template in load_voice(language).procedures.items():
        p = FIXES[p_id]
        for field in ("office", "fee", "time_limit"):
            if f"{{{field}}}" in template:
                assert getattr(p, field) is not None, f"{p_id} has no {field} but its template says it"
        if "{bring}" in template:
            assert p.bring, p_id
        if p.cautions:
            assert "{caution}" in template, f"{p_id}: every caution is spoken (e.g. the Aadhaar lifetime limit)"


@pytest.mark.parametrize("language", ["hi", "mr"])
def test_every_knowledge_base_value_is_worded_in_hindi_and_marathi(language: str) -> None:
    t = load_voice(language)
    for p in FIXES.values():
        for name, fact in p.facts().items():
            assert fact.value in t.values, f"{language}: no wording for {p.id} {name} {fact.value!r}"
            assert not re.search(r"[A-Za-z]", t.values[fact.value]), f"{language}: Latin letters in {fact.value!r}"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("p_id", sorted(p for p in FIXES if FIXES[p].office))
def test_filled_sentence_names_the_steps_exact_office_and_no_other(language: str, p_id: str) -> None:
    t = load_voice(language)
    say = lambda value: t.values.get(value, value)  # noqa: E731
    sentence = step_voice(_step(p_id), {"i1": ISSUE}, {}, language)
    office = say(FIXES[p_id].office.value)
    assert office in sentence, sentence
    rest = sentence.replace(office, "")
    others = {say(p.office.value) for p in FIXES.values() if p.office and p.office.value != FIXES[p_id].office.value}
    assert not [o for o in others if o in rest], (sentence, [o for o in others if o in rest])
    assert "{" not in sentence and "None" not in sentence


@pytest.mark.parametrize("language", LANGUAGES)
def test_confirm_at_the_office_is_said_once_at_the_end_if_anything_is_unverified(language: str) -> None:
    t = load_voice(language)
    for p_id in FIXES:
        sentence = step_voice(_step(p_id), {"i1": ISSUE}, {}, language)
        unverified = any(f.status == "unverified" for f in FIXES[p_id].facts().values())
        refers = any(f.value in OFFICE_REFERRALS for f in FIXES[p_id].cautions)
        assert sentence.count(t.unverified) == (1 if unverified and not refers else 0), (p_id, sentence)
        if t.unverified in sentence:
            assert sentence.endswith(t.unverified), sentence
    assert t.unverified in step_voice(_step("aadhaar_name_correction"), {"i1": ISSUE}, {}, language)  # fee, limit
    assert t.unverified not in step_voice(_step("ration_card_name_correction"), {"i1": ISSUE}, {}, language)
    assert t.unverified not in step_voice(_step("self_declaration"), {"i1": ISSUE}, {}, language)  # no duplicate


def test_office_referral_cautions_exist_in_the_knowledge_base() -> None:
    cautions = {f.value for p in FIXES.values() for f in p.cautions}
    assert OFFICE_REFERRALS <= cautions


@pytest.mark.parametrize("language", LANGUAGES)
def test_document_names_are_only_ever_a_label(language: str) -> None:
    """'{documents}' is followed by ':' (a label) or is a stand-alone list in a question (after ':' or '?'):
    it never needs an inflected form."""
    for name, template in _all_templates(language).items():
        for m in re.finditer(r"\{documents\}", template):
            after, before = template[m.end():m.end() + 1], template[:m.start()].rstrip()
            assert after == ":" or (name.startswith("questions.") and before.endswith((":", "?"))), (name, template)


def _eval_issues() -> list[PlannerIssue]:
    out = []
    for path in sorted(EVAL.glob("EV*/ground_truth.json")):
        gt = json.loads(path.read_text(encoding="utf-8"))
        hh = build_household(extractions_from_truth(gt), date.fromisoformat(gt["reference_date"]))
        out += planner_issues(hh, evaluate(hh))
    return out


def test_questions_and_office_sentences_never_show_internal_ids() -> None:
    issues = _eval_issues()
    mismatches = [i for i in issues if len(set(i.values.values())) > 1]
    assert len(mismatches) >= 10
    internal = re.compile(r"\b(?:" + "|".join(DOC_TYPES) + r")(?:_m\d+)?\b|_m\d\b|\bi\d+\b|\br\d+\b|\bx\d+\b")
    for language in LANGUAGES:
        names = load_voice(language).documents.values()
        for issue in issues:
            sentences = [step_voice(FixStep(kind="ask_at_office", issue_ids=[issue.id]), {issue.id: issue}, {}, language)]
            if issue in mismatches:
                sentences += [question_text(issue, kind, language) for kind in ("which_is_correct", "compare")]
            for sentence in sentences:
                assert not internal.search(sentence), (language, sentence)
                assert not any(d in sentence for d in issue.documents), (language, sentence)
                assert any(n in sentence for n in names), (language, sentence)


def test_a_question_shows_the_script_where_the_values_differ() -> None:
    marathi_only = ISSUE.model_copy(update={"values": {"rc": "मीरा किरण ठोंबरे / Meera Kiran Thombre",
                                                       "id_m1": "मीरा किरण ठॉंबरे / Meera Kiran Thombre"}})
    assert "ठॉंबरे" in question_text(marathi_only, "compare", "en")  # English is the same on both: show Marathi
    assert "Suneel" in question_text(ISSUE, "which_is_correct", "en") and "सुनिल" in question_text(ISSUE, "which_is_correct", "mr")


@pytest.mark.parametrize("language", LANGUAGES)
def test_time_limits_are_never_a_promise(language: str) -> None:
    t = load_voice(language)
    assert "{time_limit}" in t.law_sets
    for name, template in _all_templates(language).items():
        if "{time_limit}" in template and name != "law_sets":
            assert t.law_sets in template, f"{name}: a time limit is only said as '{t.law_sets}'"
    if language == "en":
        for name, template in _all_templates("en").items():
            assert not re.search(r"\b(within|will|guarantee|in \{time_limit\}|takes \{time_limit\})", template, re.I), name
    sentence = step_voice(_step("income_certificate_new"), {"i1": ISSUE}, {}, language)
    assert t.law_sets.format(time_limit=t.values.get(FIXES["income_certificate_new"].time_limit.value,
                                                     FIXES["income_certificate_new"].time_limit.value)) in sentence


def test_finalized_plan_has_a_sentence_for_every_step() -> None:
    steps = [FixStep(kind="question", issue_ids=["i1"], question_kind="which_is_correct", question="?"),
             FixStep(**{**_step("aadhaar_name_correction").model_dump(), "cautions": [], "fee": None}),
             FixStep(kind="ask_at_office", issue_ids=["i1"])]
    finalize(steps, [ISSUE], "hi")
    assert all(s.voice for s in steps) and "आधार" in steps[1].voice
    assert steps[1].cautions and steps[1].fee  # completed from the procedure
