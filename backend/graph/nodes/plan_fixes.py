"""plan_fixes node: the fix planner agent, with ask_family as a LangGraph interrupt.

When the agent asks the family a question, the graph pauses with the question (screen text, spoken text,
numbered options). It resumes with the chosen option's index. On resume LangGraph re-runs this node from the
start: every agent turn is in the disk cache (keyed by the full conversation), so the replay is free and
identical up to the question, where `interrupt()` now returns the family's answer.
"""

import json
from typing import Any, Callable

from langgraph.types import interrupt

from agents.answers import question_prompt
from agents.fix_planner import plan_fixes
from agents.tools import NOT_SURE
from agents.voice import documents_with_values, member_text
from rules.engine import SchemeResult
from schemas.fixes import FixPlan, PlannerIssue
from schemas.household import Household


def question_payload(issue: PlannerIssue, kind: str, language: str) -> dict[str, Any]:
    prompt = question_prompt(issue, kind, language)
    return {
        "question_id": f"{issue.id}:{kind}",
        "issue_id": issue.id, "issue_type": issue.type, "severity": issue.severity, "kind": kind,
        "member": member_text(issue, language), "screen": prompt.screen, "speech": prompt.speech,
        "documents": documents_with_values(issue, language), "options": prompt.options, "shown": prompt.shown,
        "english_only": prompt.english_only,
        # side by side for 'confirm' name questions: document type -> value
        "values": [{"document_type": issue.documents[d], "value": v} for d, v in issue.values.items()],
    }


def question_key(issue: PlannerIssue, kind: str) -> str:
    """Stable across re-plans (issue ids are renumbered when the issues change): the issue type, the question
    kind and each document's value. If a close-up changes a value, the key changes and the family is asked again."""
    return json.dumps([issue.type, kind, sorted(issue.values.items())], ensure_ascii=False)


def remembered_answers(plan: FixPlan, issues: list[PlannerIssue]) -> dict[str, str]:
    by_id = {i.id: i for i in issues}
    return {question_key(by_id[s.issue_ids[0]], s.question_kind): s.answer for s in plan.steps
            if s.kind == "question" and s.answer and s.question_kind and s.issue_ids and s.issue_ids[0] in by_id}


def interrupting_family(language: str, remembered: dict[str, str] | None = None
                        ) -> Callable[[PlannerIssue, str, str, list[str]], str]:
    """Asks by pausing the graph, unless the family already answered the same question before a re-plan."""
    remembered = remembered or {}

    def ask(issue: PlannerIssue, kind: str, question: str, options: list[str]) -> str:
        earlier = remembered.get(question_key(issue, kind))
        if earlier in options:
            return earlier
        payload = question_payload(issue, kind, language)
        index = interrupt(payload)  # pauses the graph; returns the option index on resume
        try:
            return payload["options"][int(index)]
        except (TypeError, ValueError, IndexError):
            return NOT_SURE

    return ask


def run_planner(household: Household, results: list[SchemeResult], language: str, llm: Callable[..., Any],
                waiting: frozenset[str] = frozenset(), remembered: dict[str, str] | None = None) -> FixPlan:
    return plan_fixes(household, results, interrupting_family(language, remembered), llm=llm, language=language,
                      waiting=waiting)
