"""Fix planner: the one true agent. A tool loop over the household's issues -> a verified FixPlan.

1. planner_issues: household issues (and the rules engine's caste-certificate gaps) -> PlannerIssue list.
2. The agent (task "agent") calls tools from agents/tools.py and finishes with submit_plan.
3. assemble: questions come from the ask_family log; every fact gets its status and source from data/fixes.
4. verify (deterministic): every office, fee, time limit, document and caution must be the cited
   procedure's own; mismatches must be asked about first and only the wrong documents corrected.
   A rejected plan is sent back once with the errors; then the fallback (a plain list of matching
   procedures) is used.
5. finalize: each fix step gets all of its procedure's facts (the agent may leave some out, never change
   them), their status and source, and a voice sentence from data/templates/voice (agents/voice.py).
   The agent never writes text the family hears.
6. order_steps: questions first ('confirm' issues first), then the slowest fixes, then fixes grouped
   by office into one visit each, then 'ask at the office'.
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable

from clients.llm import ChatResponse, LLMError, TokenUsage, chat
from openai import APIError
from pydantic import ValidationError
from rules.engine import SchemeResult
from schemas.fixes import FactUsed, FixPlan, FixProcedure, FixStep, PlannerIssue
from schemas.household import Household
from vision.text import comparison_key

from agents.tools import (MISMATCHES, NOT_SURE, TOOLS, FamilyResponder, ToolBox, load_fixes, procedures_for,
                          wrong_doc_types)
from agents.voice import plan_voice, question_text

logger = logging.getLogger(__name__)

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "fix_planner.md").read_text(encoding="utf-8")
MAX_TURNS = 14
PLANNED_TYPES = ("name_mismatch", "dob_mismatch", "not_on_ration_card", "missing_document", "expired")

Chat = Callable[..., ChatResponse]


# ---------- 1. issues ----------

def _member_name(hh: Household, member_id: str | None, devanagari: bool = False) -> str | None:
    if member_id is None:
        return None
    m = hh.member(member_id)
    return (m.name_mr or m.name_en) if devanagari else (m.name_en or m.name_mr)


def planner_issues(hh: Household, results: list[SchemeResult] = ()) -> list[PlannerIssue]:
    """The issues to plan for. Recapture (unreadable) and info notes are handled elsewhere."""
    out: list[PlannerIssue] = []

    def add(**kw: Any) -> None:
        out.append(PlannerIssue(id=f"i{len(out) + 1}", **kw))

    for i in hh.issues:
        if i.type not in PLANNED_TYPES or i.severity == "info":
            continue
        docs = {d: hh.documents[d].doc_type for d in i.documents if d in hh.documents}
        values: dict[str, str] = {}
        if i.type == "name_mismatch":
            for d in docs:
                parts = [i.evidence["names"][s][d] for s in ("mr", "en") if d in i.evidence["names"].get(s, {})]
                if parts:
                    values[d] = " / ".join(parts)
        elif i.type == "dob_mismatch":
            values = {d: v for d, v in i.evidence["dates_of_birth"].items() if d in docs}
        doc_type = {"missing_document": i.evidence.get("document_type"), "expired": "income_certificate",
                    "not_on_ration_card": "ration_card"}.get(i.type)
        add(type=i.type, severity=i.severity, member_id=i.member_id, member_name=_member_name(hh, i.member_id),
            member_name_mr=_member_name(hh, i.member_id, devanagari=True),
            documents=docs, document_type=doc_type, values=values, detail=i.message)

    # Ramai Awas: an adult whose own caste certificate is missing while another member has a qualifying one.
    for r in results:
        if r.scheme_id != "ramai_awas" or r.outcome != "check_at_office":
            continue
        m = hh.member(r.member_id)
        if (m.age or 0) >= 18 and any(x.check == "caste_applicant" and x.outcome == "check_at_office" for x in r.rules):
            add(type="missing_document", severity="blocker", member_id=m.member_id, member_name=_member_name(hh, m.member_id),
                member_name_mr=_member_name(hh, m.member_id, devanagari=True), documents={}, document_type="caste_certificate",
                detail=f"{m.name_en or m.member_id} has no caste certificate of their own (needed for Ramai Awas).")
    return out


# ---------- 3. assembling ----------

def _facts(p: FixProcedure, step: FixStep) -> list[FactUsed]:
    used = []
    for name, f in p.facts().items():
        used_here = ((name == "office" and step.office == f.value) or (name == "fee" and step.fee == f.value)
                     or (name == "time_limit" and step.time_limit == f.value)
                     or (name.startswith("bring") and f.value in step.bring)
                     or (name.startswith("caution") and f.value in step.cautions))
        if used_here:
            used.append(FactUsed(fact=name, value=f.value, status=f.status, source_url=f.source_url))
    return used


def question_steps(issues: list[PlannerIssue], toolbox: ToolBox) -> list[FixStep]:
    steps = []
    for issue in issues:
        for q in toolbox.answers.get(issue.id, []):
            steps.append(FixStep(kind="question", issue_ids=[issue.id], member_id=issue.member_id, question=q["question"],
                                 question_kind=q["kind"], options=q["options"], answer=q["answer"]))
    return steps


def assemble(draft: list[dict[str, Any]], issues: list[PlannerIssue], toolbox: ToolBox) -> tuple[list[FixStep], list[str]]:
    errors, steps = [], question_steps(issues, toolbox)
    fixes = load_fixes()
    for n, raw in enumerate(draft, 1):
        try:
            step = FixStep.model_validate(raw)
        except ValidationError as e:
            errors.append(f"step {n}: invalid ({e.error_count()} errors: {e.errors()[0]['msg']})")
            continue
        if step.procedure_id in fixes:
            step.facts = _facts(fixes[step.procedure_id], step)
        steps.append(step)
    return steps, errors


# ---------- 4. verification ----------

def _answers(toolbox: ToolBox, issue_id: str, kind: str) -> list[str]:
    return [q["answer"] for q in toolbox.answers.get(issue_id, []) if q["kind"] == kind]


def _resolved_by_questions(issue: PlannerIssue, toolbox: ToolBox) -> bool:
    return issue.severity == "confirm" and "same" in [comparison_key(a) for a in _answers(toolbox, issue.id, "compare")]


def verify(steps: list[FixStep], issues: list[PlannerIssue], toolbox: ToolBox) -> list[str]:
    """Deterministic checks; returns the errors (empty: the plan is accepted)."""
    fixes = load_fixes()
    by_id = {i.id: i for i in issues}
    errors: list[str] = []
    covered: set[str] = set()  # by a fix or ask_at_office step; an optional declaration alone doesn't cover an issue
    for n, s in enumerate(steps, 1):
        if s.kind == "question":
            continue
        where = f"step {n} ({s.procedure_id or s.kind})"
        unknown = [i for i in s.issue_ids if i not in by_id]
        if unknown or not s.issue_ids:
            errors.append(f"{where}: unknown or missing issue ids {unknown}")
        if not (fixes.get(s.procedure_id or "") and fixes[s.procedure_id].optional):
            covered |= set(s.issue_ids)
        if s.kind == "ask_at_office":
            if s.procedure_id or s.office or s.fee or s.time_limit or s.bring:
                errors.append(f"{where}: an ask_at_office step has no procedure, office, fee, time limit or documents")
            continue
        p = fixes.get(s.procedure_id or "")
        if p is None:
            errors.append(f"{where}: procedure {s.procedure_id!r} is not in data/fixes")
            continue
        for i in s.issue_ids:
            issue = by_id.get(i)
            if issue and not any(f.issue == issue.type for f in p.fixes):
                errors.append(f"{where}: {p.id} does not fix a {issue.type} ({i})")
        if s.office != (p.office.value if p.office else None):
            errors.append(f"{where}: office {s.office!r} is not the procedure's ({p.office.value if p.office else None!r})")
        if s.fee is not None and s.fee != (p.fee.value if p.fee else None):
            errors.append(f"{where}: fee {s.fee!r} is not in the procedure")
        if s.time_limit is not None and s.time_limit != (p.time_limit.value if p.time_limit else None):
            errors.append(f"{where}: time limit {s.time_limit!r} is not in the procedure")
        for b in s.bring:
            if b not in [f.value for f in p.bring]:
                errors.append(f"{where}: document to bring {b!r} is not in the procedure")
        for c in s.cautions:
            if c not in [f.value for f in p.cautions]:
                errors.append(f"{where}: caution {c!r} is not in the procedure")
        if p.id == "self_declaration" and not s.declaration:
            errors.append(f"{where}: a self-declaration step needs the text from draft_declaration")
        # Mismatches: asked first, and only the documents the family's answer shows to be wrong are corrected.
        for i in s.issue_ids:
            issue = by_id.get(i)
            if not issue or issue.type not in MISMATCHES or p.optional:
                continue
            answers = [a for a in _answers(toolbox, i, "which_is_correct") if a != NOT_SURE]
            if not answers:
                errors.append(f"{where}: {i} is a mismatch; ask the family which value is correct before fixing")
            elif p.corrects not in wrong_doc_types(issue, answers[-1]):
                errors.append(f"{where}: the family said {answers[-1]!r} is correct, so the {p.corrects} is not wrong ({i})")
    for issue in issues:
        if issue.severity == "confirm" and not _answers(toolbox, issue.id, "compare"):
            errors.append(f"{issue.id} has severity confirm: ask the family to compare the documents first (kind 'compare')")
        if issue.id not in covered and not _resolved_by_questions(issue, toolbox):
            errors.append(f"{issue.id} ({issue.type}) is not covered by any step (a fix, or ask_at_office if no "
                          "procedure fixes the wrong document; an optional declaration alone is not enough)")
    return errors


# ---------- 5. finalizing ----------

def finalize(steps: list[FixStep], issues: list[PlannerIssue], language: str) -> list[FixStep]:
    """Complete each verified fix step with all of its procedure's facts, then fill the voice sentences."""
    fixes = load_fixes()
    for s in steps:
        p = fixes.get(s.procedure_id or "") if s.kind == "fix" else None
        if p is not None:
            s.office = p.office.value if p.office else None
            s.bring = [f.value for f in p.bring]
            s.fee = p.fee.value if p.fee else None
            s.time_limit = p.time_limit.value if p.time_limit else None
            s.cautions = [f.value for f in p.cautions]
            s.facts = _facts(p, s)
    for s, sentence in zip(steps, plan_voice(steps, issues, language)):
        s.voice = sentence
    return steps


# ---------- 6. ordering ----------

def order_steps(steps: list[FixStep], issues: list[PlannerIssue]) -> list[FixStep]:
    fixes = load_fixes()
    confirm = {i.id for i in issues if i.severity == "confirm"}
    questions = sorted((s for s in steps if s.kind == "question"), key=lambda s: not (set(s.issue_ids) & confirm))
    fix_steps = [s for s in steps if s.kind == "fix"]
    office_of = {}  # issue id -> office of its (non-optional) fix, so a declaration joins that visit
    for s in fix_steps:
        if s.office:
            for i in s.issue_ids:
                office_of.setdefault(i, s.office)
    slow = {s.office for s in fix_steps if fixes.get(s.procedure_id or "") and fixes[s.procedure_id].slowest}
    offices: list[str | None] = []
    for s in fix_steps:
        office = s.office or next((office_of[i] for i in s.issue_ids if i in office_of), None)
        if office not in offices:
            offices.append(office)
    offices.sort(key=lambda o: (o not in slow, o is None))

    def office(s: FixStep) -> str | None:
        return s.office or next((office_of[i] for i in s.issue_ids if i in office_of), None)

    def key(s: FixStep) -> tuple[int, int]:
        p = fixes.get(s.procedure_id or "")
        return offices.index(office(s)), int(bool(p and p.optional))

    ordered = sorted(fix_steps, key=key)
    for s in ordered:
        s.visit = offices.index(office(s)) + 1
    return questions + ordered + [s for s in steps if s.kind == "ask_at_office"]


# ---------- fallback ----------

def fallback_steps(issues: list[PlannerIssue], language: str = "en") -> list[FixStep]:
    """A plain list of matching procedures (no agent). Mismatches get the (unanswered) question and every
    candidate fix: the family checks which document is wrong first."""
    steps: list[FixStep] = []
    for issue in issues:
        if issue.type in MISMATCHES and len(set(issue.values.values())) > 1:
            steps.append(FixStep(kind="question", issue_ids=[issue.id], member_id=issue.member_id,
                                 question=question_text(issue, "which_is_correct", language), question_kind="which_is_correct",
                                 options=[*sorted(set(issue.values.values())), NOT_SURE]))
        doc_types = sorted(set(issue.documents.values())) if issue.type in MISMATCHES else [issue.document_type]
        found = [p for t in doc_types for p in procedures_for(issue.type, t) if not p.optional]
        if not found:
            steps.append(FixStep(kind="ask_at_office", issue_ids=[issue.id], member_id=issue.member_id))
        for p in {p.id: p for p in found}.values():
            steps.append(FixStep(kind="fix", issue_ids=[issue.id], member_id=issue.member_id, procedure_id=p.id,
                                 office=p.office.value if p.office else None))
    return order_steps(finalize(steps, issues, language), issues)


# ---------- 2. the agent ----------

def _add_usage(total: TokenUsage, u: TokenUsage) -> None:
    total.prompt_tokens += u.prompt_tokens
    total.completion_tokens += u.completion_tokens
    total.total_tokens += u.total_tokens


def plan_fixes(hh: Household, results: list[SchemeResult], family: FamilyResponder, *, llm: Chat = chat,
               language: str = "en", overrides: dict[str, Any] | None = None, max_turns: int = MAX_TURNS) -> FixPlan:
    issues = planner_issues(hh, results)
    if not issues:
        return FixPlan(steps=[], source="agent", language=language)
    toolbox = ToolBox(issues, family, language)
    members = [{"member_id": m.member_id, "name": m.name_en or m.name_mr, "relation": m.relation_en,
                "on_ration_card": m.on_ration_card, "age": m.age} for m in hh.members]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": "Members:\n" + json.dumps(members, ensure_ascii=False) + "\n\nIssues:\n"
                                    + json.dumps([i.model_dump() for i in issues], ensure_ascii=False)},
    ]
    usage, trace = TokenUsage(), []
    attempts, last_errors = 0, []
    for turn in range(1, max_turns + 1):
        try:
            resp = llm(messages, task="agent", tools=TOOLS, overrides=overrides)
        except (LLMError, APIError) as e:
            trace.append({"turn": turn, "error": str(e)})
            logger.warning("fix planner call failed: %s", e)
            break
        _add_usage(usage, resp.usage)
        entry: dict[str, Any] = {"turn": turn, "reasoning": resp.reasoning, "content": resp.content, "calls": []}
        trace.append(entry)
        if not resp.tool_calls:
            messages += [{"role": "assistant", "content": resp.content or ""},
                         {"role": "user", "content": "Use the tools, and finish by calling submit_plan."}]
            continue
        messages.append({"role": "assistant", "content": resp.content or "", "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in resp.tool_calls]})
        for c in resp.tool_calls:
            if c.name != "submit_plan":
                result = toolbox.call(c.name, c.arguments)
            else:
                attempts += 1
                try:
                    draft = json.loads(c.arguments).get("steps", [])
                except (json.JSONDecodeError, AttributeError) as e:
                    draft, parse_error = [], [f"submit_plan arguments are not valid JSON: {e}"]
                else:
                    parse_error = []
                steps, assemble_errors = assemble(draft, issues, toolbox)
                last_errors = parse_error + assemble_errors + verify(steps, issues, toolbox)
                if not last_errors:
                    entry["calls"].append({"tool": c.name, "args": c.arguments, "result": "accepted"})
                    return FixPlan(steps=order_steps(finalize(steps, issues, language), issues), language=language,
                                   source="agent" if attempts == 1 else "agent_retry",
                                   attempts=attempts, turns=turn, trace=trace, usage=usage,
                                   verification_errors=[] if attempts == 1 else first_errors)
                if attempts == 1:
                    first_errors = last_errors
                    result = {"rejected": last_errors, "instruction": "Fix these errors and call submit_plan again."}
                else:
                    entry["calls"].append({"tool": c.name, "args": c.arguments, "result": {"rejected": last_errors}})
                    return FixPlan(steps=fallback_steps(issues, language), source="fallback", language=language,
                                   attempts=attempts, turns=turn, trace=trace, usage=usage, verification_errors=last_errors)
            entry["calls"].append({"tool": c.name, "args": c.arguments, "result": result})
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, ensure_ascii=False)})
    return FixPlan(steps=fallback_steps(issues, language), source="fallback", language=language, attempts=attempts,
                   turns=len(trace), trace=trace, usage=usage,
                   verification_errors=last_errors or ["the agent did not submit a plan"])
