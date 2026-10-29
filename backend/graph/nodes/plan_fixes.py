"""plan_fixes node: the fix planner agent, with ask_family as a LangGraph interrupt.

When the agent asks the family a question, the graph pauses with the question (screen text, spoken text,
numbered options). It resumes with the chosen option's index. On resume LangGraph re-runs this node from the
start: every agent turn is in the disk cache (keyed by the full conversation), so the replay is free and
identical up to the question, where `interrupt()` now returns the family's answer.
"""

from typing import Any, Callable

from langgraph.types import interrupt

from agents.answers import question_prompt
from agents.fix_planner import plan_fixes
from agents.tools import NOT_SURE
from agents.voice import documents_with_values
from rules.engine import SchemeResult
from schemas.fixes import FixPlan, PlannerIssue
from schemas.household import Household


def question_payload(issue: PlannerIssue, kind: str, language: str) -> dict[str, Any]:
    prompt = question_prompt(issue, kind, language)
    return {
        "question_id": f"{issue.id}:{kind}",
        "issue_id": issue.id, "issue_type": issue.type, "severity": issue.severity, "kind": kind,
        "member": issue.member_name, "screen": prompt.screen, "speech": prompt.speech,
        "documents": documents_with_values(issue, language), "options": prompt.options, "shown": prompt.shown,
        "english_only": prompt.english_only,
        # side by side for 'confirm' name questions: document type -> value
        "values": [{"document_type": issue.documents[d], "value": v} for d, v in issue.values.items()],
    }


def interrupting_family(language: str) -> Callable[[PlannerIssue, str, str, list[str]], str]:
    def ask(issue: PlannerIssue, kind: str, question: str, options: list[str]) -> str:
        payload = question_payload(issue, kind, language)
        index = interrupt(payload)  # pauses the graph; returns the option index on resume
        try:
            return payload["options"][int(index)]
        except (TypeError, ValueError, IndexError):
            return NOT_SURE

    return ask


def run_planner(household: Household, results: list[SchemeResult], language: str, llm: Callable[..., Any]) -> FixPlan:
    return plan_fixes(household, results, interrupting_family(language), llm=llm, language=language)
