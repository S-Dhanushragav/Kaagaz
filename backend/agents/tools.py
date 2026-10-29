"""Tools for the fix planner. Deterministic; every fact comes from data/fixes/*.yaml.

Tools: lookup_fix_procedure, get_office_info, ask_family, draft_declaration (and submit_plan, which
the planner itself handles). Results are plain dicts, sent to the model as JSON.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml

from schemas.fixes import FixProcedure, PlannerIssue
from vision.text import comparison_key

DATA = Path(__file__).resolve().parents[2] / "data"
FIXES_DIR = DATA / "fixes"
DECLARATION_TEMPLATE = DATA / "templates" / "declarations" / "one_and_same.md"
ASK_AT_OFFICE = "No procedure in the knowledge base for this: tell the family to ask at the office."
NOT_SURE = "not sure"
MISMATCHES = ("name_mismatch", "dob_mismatch")
COMPARE_OPTIONS = ["same", "different"]

# (issue, kind, question, options) -> the family's answer: one of the options
FamilyResponder = Callable[[PlannerIssue, str, str, list[str]], str]


@lru_cache
def load_fixes() -> dict[str, FixProcedure]:
    procedures = {}
    for path in sorted(FIXES_DIR.glob("*.yaml")):
        p = FixProcedure.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if p.id != path.stem:
            raise ValueError(f"{path.name}: id {p.id!r} does not match the file name")
        procedures[p.id] = p
    return procedures


def public(p: FixProcedure) -> dict[str, Any]:
    """What the agent sees of a procedure: values and their status (no developer notes)."""
    fact = lambda f: None if f is None else {"value": f.value, "status": f.status}  # noqa: E731
    return {
        "id": p.id, "title": p.title, "optional": p.optional, "slowest": p.slowest, "corrects": p.corrects,
        "office": fact(p.office), "steps": p.steps, "bring": [fact(f) for f in p.bring], "fee": fact(p.fee),
        "time_limit": fact(p.time_limit), "cautions": [fact(f) for f in p.cautions], "status": p.status,
    }


def procedures_for(issue_type: str, wrong_document_type: str | None) -> list[FixProcedure]:
    """Procedures that fix this issue type for this document type (plus 'any'-document ones)."""
    return [p for p in load_fixes().values()
            if any(f.issue == issue_type and f.wrong_document in (wrong_document_type, "any") for f in p.fixes)]


def value_matches(value: str, answer: str) -> bool:
    """The answer is the whole value or one script of it ('मराठी / English')."""
    return comparison_key(answer) in {comparison_key(value), *(comparison_key(p) for p in value.split(" / "))}


def wrong_doc_types(issue: PlannerIssue, answer: str) -> set[str]:
    """Document types whose value differs from the family's answer."""
    return {issue.documents[d] for d, v in issue.values.items() if not value_matches(v, answer)}


def fill_declaration(name: str, what: str, values: list[str]) -> str:
    template = DECLARATION_TEMPLATE.read_text(encoding="utf-8")
    return template.format(name=name, what=what, values="\n".join(f"- {v}" for v in values))


class ToolBox:
    """The tools for one household's planning run; keeps a log of every call."""

    def __init__(self, issues: list[PlannerIssue], family: FamilyResponder, language: str = "en") -> None:
        self.issues = {i.id: i for i in issues}
        self.family = family
        self.language = language
        self.log: list[dict[str, Any]] = []  # {"tool", "args", "result"}
        self.answers: dict[str, list[dict[str, Any]]] = {}  # issue id -> questions asked, with answers, in order

    def call(self, name: str, arguments: str) -> dict[str, Any]:
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError as e:
            result: dict[str, Any] = {"error": f"arguments are not valid JSON: {e}"}
        else:
            handler = getattr(self, f"_{name}", None)
            if handler is None or name == "submit_plan":
                result = {"error": f"unknown tool {name!r}"}
            else:
                try:
                    result = handler(**args)
                except TypeError as e:
                    result = {"error": f"bad arguments for {name}: {e}"}
        self.log.append({"tool": name, "args": arguments, "result": result})
        return result

    # ---------- tools ----------

    def _lookup_fix_procedure(self, issue_type: str, wrong_document_type: str | None = None) -> dict[str, Any]:
        found = procedures_for(issue_type, wrong_document_type)
        if not found:
            return {"procedures": [], "message": ASK_AT_OFFICE}
        return {"procedures": [public(p) for p in found]}

    def _get_office_info(self, office_type: str) -> dict[str, Any]:
        key = comparison_key(office_type)
        found = [p for p in load_fixes().values() if p.office and comparison_key(p.office.value) == key]
        if not found:
            offices = sorted({p.office.value for p in load_fixes().values() if p.office})
            return {"error": f"office type {office_type!r} is not in the knowledge base", "known_office_types": offices}
        return {"office_type": found[0].office.value, "status": found[0].office.status,
                "procedures": [{"id": p.id, "title": p.title, "bring": [f.value for f in p.bring],
                                "time_limit": p.time_limit.value if p.time_limit else None} for p in found],
                "note": "Office types only; no addresses."}

    def _ask_family(self, issue_id: str, kind: str) -> dict[str, Any]:
        """The question and its options come from the voice templates and the issue, never from the agent."""
        from agents.voice import question_text  # voice imports this module

        issue = self.issues.get(issue_id)
        if issue is None:
            return {"error": f"unknown issue id {issue_id!r}"}
        if kind not in ("which_is_correct", "compare"):
            return {"error": "kind must be 'which_is_correct' or 'compare'"}
        if kind == "which_is_correct" and len(set(issue.values.values())) < 2:
            return {"error": f"{issue_id} has no differing values to choose from"}
        values = sorted(set(issue.values.values())) if kind == "which_is_correct" else COMPARE_OPTIONS
        options = [*values, NOT_SURE]
        question = question_text(issue, kind, self.language)
        answer = self.family(issue, kind, question, options)
        if answer not in options:
            answer = NOT_SURE
        self.answers.setdefault(issue_id, []).append({"kind": kind, "question": question, "options": options,
                                                      "answer": answer})
        return {"issue_id": issue_id, "kind": kind, "options": options, "answer": answer}

    def _draft_declaration(self, issue_id: str, member_name: str, values: list[str]) -> dict[str, Any]:
        issue = self.issues.get(issue_id)
        if issue is None or issue.type not in ("name_mismatch", "dob_mismatch"):
            return {"error": "a declaration is only for a name or date-of-birth mismatch"}
        known = {comparison_key(v) for v in issue.values.values()}
        if not values or any(comparison_key(v) not in known for v in values):
            return {"error": "values must be the differing values of this issue", "values": sorted(set(issue.values.values()))}
        what = "names" if issue.type == "name_mismatch" else "dates of birth"
        return {"declaration": fill_declaration(member_name, what, values),
                "status": "unverified", "caution": "Acceptance of the declaration is up to the office."}


# ---------- tool schemas (OpenAI function-calling format) ----------

def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


_STR = {"type": "string"}
_STRS = {"type": "array", "items": {"type": "string"}}
_NULL_STR = {"type": ["string", "null"]}

STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["fix", "ask_at_office"]},
        "issue_ids": _STRS,
        "member_id": _NULL_STR,
        "procedure_id": {**_NULL_STR, "description": "id from lookup_fix_procedure; null for ask_at_office"},
        "office": {**_NULL_STR, "description": "the procedure's office value, exactly"},
        "bring": {**_STRS, "description": "the procedure's bring values, exactly"},
        "fee": {**_NULL_STR, "description": "the procedure's fee value exactly, or null"},
        "time_limit": {**_NULL_STR, "description": "the procedure's time_limit value exactly, or null"},
        "cautions": {**_STRS, "description": "the procedure's caution values, exactly"},
        "declaration": {**_NULL_STR, "description": "text from draft_declaration, if one was drafted"},
    },
    "required": ["kind", "issue_ids", "member_id", "procedure_id", "office", "bring", "fee", "time_limit",
                 "cautions", "declaration"],
    "additionalProperties": False,
}

TOOLS = [
    _fn("lookup_fix_procedure", "Find the procedure(s) that fix an issue type when a given document is wrong. "
        "Returns nothing for combinations the knowledge base doesn't cover.",
        {"issue_type": _STR, "wrong_document_type": {**_STR, "description": "identity_card, ration_card, "
                                                                            "income_certificate or caste_certificate"}},
        ["issue_type", "wrong_document_type"]),
    _fn("get_office_info", "Office type, what to bring and time limits for procedures at that office type.",
        {"office_type": _STR}, ["office_type"]),
    _fn("ask_family", "Ask the family about one issue and wait for the answer. The question and options are "
        "generated from the issue. kind 'which_is_correct': which of the differing values is right (the answer is "
        "one of the values, or 'not sure'). kind 'compare': do the documents really differ (answer 'same', "
        "'different' or 'not sure').",
        {"issue_id": _STR, "kind": {"type": "string", "enum": ["which_is_correct", "compare"]}},
        ["issue_id", "kind"]),
    _fn("draft_declaration", "Draft an optional 'one and the same person' declaration for a name or date-of-birth "
        "mismatch. Acceptance is always up to the office.",
        {"issue_id": _STR, "member_name": _STR, "values": _STRS}, ["issue_id", "member_name", "values"]),
    _fn("submit_plan", "Submit the finished plan (fix and ask_at_office steps; questions are recorded automatically).",
        {"steps": {"type": "array", "items": STEP_SCHEMA}}, ["steps"]),
]
