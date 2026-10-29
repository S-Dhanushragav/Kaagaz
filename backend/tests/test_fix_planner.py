"""Fix knowledge base, tools, and the fix planner with a scripted fake LLM."""

import json
import re
from datetime import date

import pytest

from agents.fix_planner import fallback_steps, order_steps, plan_fixes, planner_issues, verify
from agents.tools import ASK_AT_OFFICE, NOT_SURE, TOOLS, ToolBox, load_fixes
from clients.llm import ChatResponse, TokenUsage, ToolCall
from graph.nodes.build_household import build_household
from rules.engine import RuleResult, SchemeResult
from schemas.fixes import FixStep, PlannerIssue
from tests.test_household import SUNEEL_ID, SUNIL, _card, _id, _income, _no_llm

REF = date(2026, 10, 27)
FIXES = load_fixes()
NAME_LIMIT = "The name on Aadhaar can be updated only twice in a lifetime."
DOB_LIMIT = FIXES["aadhaar_dob_correction"].cautions[0].value


# ---------- knowledge base ----------

def test_knowledge_base_has_exactly_the_given_procedures_and_facts() -> None:
    assert set(FIXES) == {"aadhaar_name_correction", "aadhaar_dob_correction", "ration_card_name_correction",
                          "ration_card_add_member", "income_certificate_new", "caste_certificate_new",
                          "aadhaar_enrolment", "self_declaration"}
    for p in FIXES.values():
        assert p.last_checked == date(2026, 10, 29)
    assert FIXES["ration_card_name_correction"].fee.value == "Rs 2" and FIXES["ration_card_name_correction"].fee.status == "verified"
    assert FIXES["aadhaar_name_correction"].fee.value == "about Rs 75" and FIXES["aadhaar_name_correction"].fee.status == "unverified"
    assert FIXES["aadhaar_name_correction"].cautions[0].value == NAME_LIMIT
    assert FIXES["aadhaar_name_correction"].cautions[0].status == "unverified"
    assert "only once in a lifetime" in DOB_LIMIT and FIXES["aadhaar_dob_correction"].cautions[0].status == "verified"
    assert FIXES["aadhaar_dob_correction"].bring[0].status == "unverified"
    assert FIXES["income_certificate_new"].time_limit.value.startswith("15 days")
    assert FIXES["income_certificate_new"].office.value == "Tahsil office"
    caste = FIXES["caste_certificate_new"]
    assert caste.slowest and caste.time_limit is None  # differs by district: never a number
    assert not re.search(r"\d", " ".join([f.value for f in caste.facts().values()] + caste.steps))
    assert FIXES["aadhaar_enrolment"].status == "unverified" and FIXES["aadhaar_enrolment"].source_url is None
    assert FIXES["ration_card_add_member"].office.status == "unverified"
    assert FIXES["self_declaration"].status == "unverified" and FIXES["self_declaration"].optional
    assert all(p.fee is None for p in FIXES.values() if p.id not in ("aadhaar_name_correction", "ration_card_name_correction"))


# ---------- tools ----------

ISSUE = PlannerIssue(id="i1", type="name_mismatch", severity="blocker", member_id="r1", member_name="Sunil Ramesh Patil",
                     documents={"rc": "ration_card", "id1": "identity_card"},
                     values={"rc": "Sunil Ramesh Patil", "id1": "Suneel Ramesh Patil"}, detail="spelled differently")


def test_lookup_returns_only_knowledge_base_procedures() -> None:
    tb = ToolBox([ISSUE], lambda *a: NOT_SURE)
    ids = [p["id"] for p in tb.call("lookup_fix_procedure", json.dumps(
        {"issue_type": "name_mismatch", "wrong_document_type": "identity_card"}))["procedures"]]
    assert ids == ["aadhaar_name_correction", "self_declaration"]
    none = tb.call("lookup_fix_procedure", json.dumps({"issue_type": "name_mismatch", "wrong_document_type": "income_certificate"}))
    assert [p["id"] for p in none["procedures"]] == ["self_declaration"]
    assert tb.call("lookup_fix_procedure", json.dumps({"issue_type": "dob_mismatch", "wrong_document_type": "caste_certificate"})) \
        == {"procedures": [], "message": ASK_AT_OFFICE}
    found = tb.call("lookup_fix_procedure", json.dumps({"issue_type": "missing_document", "wrong_document_type": "caste_certificate"}))
    assert "note" not in json.dumps(found)  # developer notes (e.g. district day counts) never reach the agent
    assert "45" not in json.dumps(found)


def test_office_info_types_only_and_ask_family_always_offers_not_sure() -> None:
    tb = ToolBox([ISSUE], lambda issue, kind, q, options: options[0])
    assert tb.call("get_office_info", json.dumps({"office_type": "tahsil office"}))["office_type"] == "Tahsil office"
    assert "error" in tb.call("get_office_info", json.dumps({"office_type": "Collector office, Pune"}))
    tb.call("ask_family", json.dumps({"issue_id": "i1", "kind": "which_is_correct", "question": "Which?",
                                      "options": ["Sunil Ramesh Patil", "Suneel Ramesh Patil"]}))
    assert tb.answers["i1"][0]["options"][-1] == NOT_SURE and tb.answers["i1"][0]["answer"] == "Sunil Ramesh Patil"
    weird = ToolBox([ISSUE], lambda *a: "something else")
    assert weird.call("ask_family", json.dumps({"issue_id": "i1", "kind": "compare", "question": "Same?",
                                                "options": ["same", "different"]}))["answer"] == NOT_SURE


def test_declaration_is_a_marked_draft_with_only_the_issue_values() -> None:
    tb = ToolBox([ISSUE], lambda *a: NOT_SURE)
    ok = tb.call("draft_declaration", json.dumps({"issue_id": "i1", "member_name": "Sunil Ramesh Patil",
                                                  "values": ["Sunil Ramesh Patil", "Suneel Ramesh Patil"]}))
    assert ok["declaration"].startswith("DRAFT - acceptance is up to the office") and "Suneel Ramesh Patil" in ok["declaration"]
    assert ok["status"] == "unverified" and "up to the office" in ok["caution"]
    bad = tb.call("draft_declaration", json.dumps({"issue_id": "i1", "member_name": "X", "values": ["Anil Patil"]}))
    assert "error" in bad


# ---------- the planner, with a scripted fake LLM ----------

def _call(name: str, **args) -> ToolCall:
    return ToolCall(id=f"c{abs(hash((name, json.dumps(args, sort_keys=True)))) % 10**6}", name=name, arguments=json.dumps(args))


def _turn(*calls: ToolCall) -> ChatResponse:
    return ChatResponse(content=None, tool_calls=list(calls), reasoning="thinking", task="agent", provider="meta",
                        model="fake", usage=TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120))


class FakeLLM:
    def __init__(self, *turns: ChatResponse) -> None:
        self.turns, self.calls = list(turns), []

    def __call__(self, messages, **kwargs) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        assert kwargs["task"] == "agent" and kwargs["tools"] == TOOLS
        return self.turns.pop(0)


def _step(procedure_id: str | None, issue_ids: list[str], voice: str, kind: str = "fix", member_id: str = "r1", **override) -> dict:
    p = FIXES.get(procedure_id or "")
    step = {"kind": kind, "issue_ids": issue_ids, "member_id": member_id, "procedure_id": procedure_id,
            "office": p.office.value if p and p.office else None, "bring": [f.value for f in p.bring] if p else [],
            "fee": p.fee.value if p and p.fee else None, "time_limit": p.time_limit.value if p and p.time_limit else None,
            "cautions": [f.value for f in p.cautions] if p else [], "declaration": None, "voice": voice}
    return {**step, **override}


def household():
    """Sunil (r1): name spelled 'Suneel' on his identity card; no income certificate."""
    return build_household([_card(SUNIL), SUNEEL_ID], REF, adjudicate=_no_llm)


def family_says(answer: str):
    return lambda issue, kind, question, options: answer if answer in options else NOT_SURE


def _ids(hh) -> dict[str, str]:
    return {i.type: i.id for i in planner_issues(hh)}


ASK = _call("ask_family", issue_id="i1", kind="which_is_correct", question="Which spelling is correct?",
            options=["Sunil Ramesh Patil", "Suneel Ramesh Patil"])
AADHAAR_FIX = _step("aadhaar_name_correction", ["i1"], "Correct the name on the Aadhaar card. It can be changed only twice in a lifetime; the fee is about Rs 75.")
INCOME_FIX = _step("income_certificate_new", ["i2"], "Apply for a new income certificate; it should come within 15 days.", member_id=None)


def test_planner_issues_carry_values_and_document_types() -> None:
    issues = planner_issues(household())
    assert [(i.id, i.type, i.document_type) for i in issues] == [("i1", "name_mismatch", None),
                                                                  ("i2", "missing_document", "income_certificate")]
    assert issues[0].values == {"rc": "सुनील रमेश पाटील / Sunil Ramesh Patil", "id1": "सुनिल रमेश पाटील / Suneel Ramesh Patil"}


def test_agent_asks_first_then_plans_and_every_fact_has_status_and_source() -> None:
    llm = FakeLLM(_turn(_call("ask_family", issue_id="i1", kind="which_is_correct", question="Which spelling is correct?",
                              options=["सुनील रमेश पाटील / Sunil Ramesh Patil", "सुनिल रमेश पाटील / Suneel Ramesh Patil"])),
                  _turn(_call("lookup_fix_procedure", issue_type="name_mismatch", wrong_document_type="identity_card"),
                        _call("lookup_fix_procedure", issue_type="missing_document", wrong_document_type="income_certificate")),
                  _turn(_call("submit_plan", steps=[INCOME_FIX, AADHAAR_FIX])))
    plan = plan_fixes(household(), [], family_says("सुनील रमेश पाटील / Sunil Ramesh Patil"), llm=llm)
    assert plan.source == "agent" and plan.attempts == 1 and plan.turns == 3
    assert [s.kind for s in plan.steps] == ["question", "fix", "fix"]
    assert plan.steps[0].answer == "सुनील रमेश पाटील / Sunil Ramesh Patil"
    aadhaar = next(s for s in plan.steps if s.procedure_id == "aadhaar_name_correction")
    assert {f.fact: (f.status, f.source_url is not None) for f in aadhaar.facts} == {
        "office": ("verified", True), "fee": ("unverified", False), "caution[0]": ("unverified", False)}
    assert plan.usage.prompt_tokens == 300 and plan.trace[0]["reasoning"] == "thinking"
    tool_order = [c["tool"] for t in plan.trace for c in t["calls"]]
    assert tool_order == ["ask_family", "lookup_fix_procedure", "lookup_fix_procedure", "submit_plan"]


def test_fixing_a_mismatch_without_asking_is_rejected_then_retried() -> None:
    llm = FakeLLM(_turn(_call("submit_plan", steps=[AADHAAR_FIX, INCOME_FIX])),
                  _turn(ASK),
                  _turn(_call("submit_plan", steps=[AADHAAR_FIX, INCOME_FIX])))
    plan = plan_fixes(household(), [], family_says("Sunil Ramesh Patil"), llm=llm)
    assert plan.source == "agent_retry" and plan.attempts == 2
    assert any("ask the family which value is correct" in e for e in plan.verification_errors)
    rejected = json.loads(llm.calls[1][-1]["content"])
    assert rejected["rejected"] and "submit_plan again" in rejected["instruction"]


def test_correcting_the_document_the_family_says_is_right_is_rejected() -> None:
    hh = household()
    issues = planner_issues(hh)
    tb = ToolBox(issues, family_says("Suneel Ramesh Patil"))  # the identity card's spelling is the right one
    tb.call("ask_family", ASK.arguments)
    errors = verify([FixStep(**AADHAAR_FIX), FixStep(**INCOME_FIX)], issues, tb)
    assert any("identity_card is not wrong" in e for e in errors)


def test_aadhaar_change_without_lifetime_limit_is_rejected() -> None:
    issues = planner_issues(household())
    tb = ToolBox(issues, family_says("Sunil Ramesh Patil"))
    tb.call("ask_family", ASK.arguments)
    no_caution = FixStep(**{**AADHAAR_FIX, "cautions": []})
    no_voice = FixStep(**{**AADHAAR_FIX, "voice": "Correct the name on the Aadhaar card."})
    for step in (no_caution, no_voice):
        assert any("lifetime limit" in e for e in verify([step, FixStep(**INCOME_FIX)], issues, tb))
    assert verify([FixStep(**AADHAAR_FIX), FixStep(**INCOME_FIX)], issues, tb) == []


@pytest.mark.parametrize("override, message", [
    ({"office": "Collector office"}, "office"),
    ({"fee": "Rs 50"}, "fee"),
    ({"time_limit": "7 days"}, "time limit"),
    ({"bring": ["PAN card"]}, "document to bring"),
    ({"voice": "Apply for a new income certificate; it takes 30 days."}, "numbers"),
])
def test_invented_facts_are_rejected(override: dict, message: str) -> None:
    issues = planner_issues(household())
    tb = ToolBox(issues, family_says("Sunil Ramesh Patil"))
    tb.call("ask_family", ASK.arguments)
    errors = verify([FixStep(**AADHAAR_FIX), FixStep(**{**INCOME_FIX, **override})], issues, tb)
    assert any(message in e for e in errors)


def test_unknown_procedure_and_ask_at_office_with_facts_are_rejected() -> None:
    issues = planner_issues(household())
    tb = ToolBox(issues, family_says("Sunil Ramesh Patil"))
    tb.call("ask_family", ASK.arguments)
    invented = FixStep(**{**_step(None, ["i2"], "Go to the bank."), "procedure_id": "bank_letter", "office": "Bank"})
    office = FixStep(**_step(None, ["i2"], "Ask at the office.", kind="ask_at_office", office="Tahsil office"))
    assert any("not in data/fixes" in e for e in verify([FixStep(**AADHAAR_FIX), invented], issues, tb))
    assert any("ask_at_office" in e for e in verify([FixStep(**AADHAAR_FIX), office], issues, tb))


def test_two_rejections_fall_back_to_knowledge_base_procedures_only() -> None:
    bad = _step("income_certificate_new", ["i2"], "Apply; it takes 30 days.", member_id=None, fee="Rs 100")
    llm = FakeLLM(_turn(ASK), _turn(_call("submit_plan", steps=[AADHAAR_FIX, bad])),
                  _turn(_call("submit_plan", steps=[AADHAAR_FIX, bad])))
    plan = plan_fixes(household(), [], family_says("Sunil Ramesh Patil"), llm=llm)
    assert plan.source == "fallback" and plan.attempts == 2 and plan.verification_errors
    for s in plan.steps:
        p = FIXES.get(s.procedure_id or "")
        if s.kind == "fix":
            assert s.office == p.office.value and s.fee == (p.fee.value if p.fee else None)
            assert set(s.bring) <= {f.value for f in p.bring}
    assert {s.procedure_id for s in plan.steps if s.kind == "fix"} == {
        "aadhaar_name_correction", "ration_card_name_correction", "income_certificate_new"}  # either document may be wrong
    assert plan.steps[0].kind == "question"


def test_no_plan_within_the_turn_limit_falls_back() -> None:
    llm = FakeLLM(*[_turn(ASK) for _ in range(3)])
    plan = plan_fixes(household(), [], family_says("Sunil Ramesh Patil"), llm=llm, max_turns=3)
    assert plan.source == "fallback" and "did not submit" in plan.verification_errors[0]


def test_confirm_issue_is_asked_as_a_question_and_same_needs_no_fix() -> None:
    hh = household()
    hh.issues = [i.model_copy(update={"severity": "confirm"}) if i.type == "name_mismatch" else i for i in hh.issues]
    compare = _call("ask_family", issue_id="i1", kind="compare", question="Do these two spellings differ on the documents?",
                    options=["same", "different"])
    no_compare = FakeLLM(_turn(_call("submit_plan", steps=[INCOME_FIX])), _turn(compare),
                         _turn(_call("submit_plan", steps=[INCOME_FIX])))
    plan = plan_fixes(hh, [], family_says("same"), llm=no_compare)
    assert plan.source == "agent_retry" and any("kind 'compare'" in e for e in plan.verification_errors)
    assert [(s.kind, s.answer) for s in plan.steps] == [("question", "same"), ("fix", None)]


def test_order_questions_first_then_slowest_then_one_visit_per_office() -> None:
    issues = [PlannerIssue(id="i1", type="missing_document", severity="blocker", member_id="r1", member_name="A",
                           documents={}, document_type="identity_card", detail=""),
              PlannerIssue(id="i2", type="dob_mismatch", severity="confirm", member_id="r2", member_name="B",
                           documents={}, detail=""),
              PlannerIssue(id="i3", type="missing_document", severity="blocker", member_id="r1", member_name="A",
                           documents={}, document_type="caste_certificate", detail="")]
    steps = [FixStep(**_step("aadhaar_enrolment", ["i1"], "Enrol.")),
             FixStep(**_step(None, ["i9"], "Ask at the office.", kind="ask_at_office")),
             FixStep(**_step("income_certificate_new", ["i4"], "Apply.")),
             FixStep(**_step("aadhaar_dob_correction", ["i2"], "Correct the date of birth; only once.")),
             FixStep(kind="question", issue_ids=["i5"], question="?", voice="?"),
             FixStep(kind="question", issue_ids=["i2"], question="Compare?", voice="Compare?"),
             FixStep(**_step("caste_certificate_new", ["i3"], "Apply for a caste certificate."))]
    ordered = order_steps(steps, issues)
    assert [(s.kind, s.issue_ids[0]) for s in ordered] == [
        ("question", "i2"), ("question", "i5"),  # 'confirm' issue's question first
        ("fix", "i3"),  # slowest: caste certificate
        ("fix", "i1"), ("fix", "i2"),  # both at the Aadhaar Seva Kendra: one visit
        ("fix", "i4"), ("ask_at_office", "i9")]
    assert ordered[3].office == ordered[4].office == "Aadhaar Seva Kendra"
    assert [s.visit for s in ordered if s.kind == "fix"] == [1, 2, 2, 3]


def test_caste_certificate_gap_becomes_an_issue_only_where_ramai_needs_it() -> None:
    hh = household()

    def ramai(outcome: str, caste: str) -> SchemeResult:
        rule = RuleResult(rule_id="applicant_category", check="caste_applicant", outcome=caste, reason="", value=None,
                          status="verified", source="x", source_url=None)
        return SchemeResult(scheme_id="ramai_awas", scheme_name="Ramai Awas", member_id="r1", outcome=outcome, reasons=[],
                            rules=[rule], needs_other_proof=[], blocking_issues=[], warnings=[])

    caste = [i for i in planner_issues(hh, [ramai("check_at_office", "check_at_office")]) if i.document_type == "caste_certificate"]
    assert len(caste) == 1 and caste[0].member_id == "r1"
    assert not [i for i in planner_issues(hh, [ramai("blocked_by_issues", "blocked")]) if i.document_type == "caste_certificate"]


def test_fallback_for_an_uncovered_combination_says_ask_at_the_office() -> None:
    issue = PlannerIssue(id="i1", type="dob_mismatch", severity="blocker", member_id="r1", member_name="A",
                         documents={"cc": "caste_certificate", "cc2": "caste_certificate"},
                         values={"cc": "01/01/1990", "cc2": "02/01/1990"}, detail="dates differ")
    steps = fallback_steps([issue])
    assert [s.kind for s in steps] == ["question", "ask_at_office"]
    assert "ask at the office" in steps[-1].voice and steps[-1].office is None and not steps[-1].bring


def test_declaration_alone_does_not_cover_a_mismatch_and_must_say_acceptance_is_up_to_the_office() -> None:
    """EV025: the family's answer makes a certificate the wrong document; no procedure corrects it."""
    issue = PlannerIssue(id="i1", type="name_mismatch", severity="blocker", member_id="r1", member_name="Meera Yogesh Zodge",
                         documents={"rc": "ration_card", "cc": "caste_certificate"},
                         values={"rc": "Meera Yogesh Zodge", "cc": "Mira Yogesh Zodge"}, detail="spelled differently")
    tb = ToolBox([issue], family_says("Meera Yogesh Zodge"))
    tb.call("ask_family", json.dumps({"issue_id": "i1", "kind": "which_is_correct", "question": "Which?",
                                      "options": ["Meera Yogesh Zodge", "Mira Yogesh Zodge"]}))
    text = tb.call("draft_declaration", json.dumps({"issue_id": "i1", "member_name": "Meera Yogesh Zodge",
                                                    "values": ["Meera Yogesh Zodge", "Mira Yogesh Zodge"]}))["declaration"]
    declaration = FixStep(**_step("self_declaration", ["i1"], "Keep this paper with your documents.", declaration=text))
    errors = verify([declaration], [issue], tb)
    assert any("not covered" in e for e in errors) and any("up to the office" in e for e in errors)
    fixed = FixStep(**{**declaration.model_dump(), "voice": "A declaration may help; acceptance is up to the office."})
    office = FixStep(**_step(None, ["i1"], "Ask at the office how to correct the name on the caste certificate.",
                             kind="ask_at_office"))
    assert verify([fixed, office], [issue], tb) == []
