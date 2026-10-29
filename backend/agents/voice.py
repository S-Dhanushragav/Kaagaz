"""Voice sentences for the fix plan, from templates in data/templates/voice/{en,hi,mr}.yaml.

No model writes these sentences. Each is a template filled from a verified plan step: every placeholder
value is a knowledge-base fact (shown in the language's wording), a member's name, or document display
names. Unverified facts carry the language's "confirm at the office" marker. Questions show documents by
their display names (never internal ids) with the values that differ.
"""

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from schemas.fixes import Fact, FixStep, PlannerIssue
from vision.text import comparison_key

from agents.tools import MISMATCHES, NOT_SURE, load_fixes, wrong_doc_types

VOICE_DIR = Path(__file__).resolve().parents[2] / "data" / "templates" / "voice"
LANGUAGES = ("en", "hi", "mr")
PLACEHOLDERS = frozenset({"office", "bring", "fee", "time_limit", "caution", "member", "documents"})
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


class VoiceTemplates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str
    documents: dict[str, str]  # document type -> display name
    values: dict[str, str] = {}  # knowledge-base value -> how it is said in this language
    unverified: str  # marker after an unverified fact
    household: str  # said when a step concerns the whole household
    options: dict[str, str]  # same / different / not sure
    law_sets: str  # the only way a time limit is said; contains {time_limit}
    procedures: dict[str, str]
    ask_at_office: str
    questions: dict[str, str]  # which_is_correct, compare


@lru_cache
def load_voice(language: str) -> VoiceTemplates:
    t = VoiceTemplates.model_validate(yaml.safe_load((VOICE_DIR / f"{language}.yaml").read_text(encoding="utf-8")))
    if t.language != language:
        raise ValueError(f"{language}.yaml says language {t.language!r}")
    return t


def say(t: VoiceTemplates, fact: Fact | None) -> str:
    if fact is None:
        return ""
    text = t.values.get(fact.value, fact.value)
    return f"{text} {t.unverified}" if fact.status == "unverified" else text


def member_text(issue: PlannerIssue | None, language: str) -> str:
    if issue is None:
        return load_voice(language).household
    name = issue.member_name_mr if language != "en" and issue.member_name_mr else issue.member_name
    return name or load_voice(language).household


def document_names(doc_types: list[str], language: str) -> str:
    t = load_voice(language)
    return ", ".join(dict.fromkeys(t.documents[x] for x in doc_types if x))


def _in_script(value: str, devanagari: bool) -> str | None:
    return next((p for p in value.split(" / ") if bool(DEVANAGARI.search(p)) == devanagari), None)


def documents_with_values(issue: PlannerIssue, language: str) -> str:
    """'ration card: X; Aadhaar card: Y', in the script that shows the difference (the language's first)."""
    t = load_voice(language)
    shown = dict(issue.values)
    for dev in (language != "en", language == "en"):
        candidate = {d: _in_script(v, dev) for d, v in issue.values.items()}
        if all(candidate.values()) and len({comparison_key(v) for v in candidate.values()}) > 1:
            shown = candidate
            break
    groups: dict[str, list[str]] = {}
    for d, v in shown.items():
        groups.setdefault(v, []).append(t.documents[issue.documents[d]])
    return "; ".join(f"{', '.join(dict.fromkeys(names))}: {v}" for v, names in groups.items())


def question_text(issue: PlannerIssue, kind: str, language: str) -> str:
    t = load_voice(language)
    return t.questions[kind].format(member=member_text(issue, language), documents=documents_with_values(issue, language))


def option_text(option: str, language: str) -> str:
    return load_voice(language).options.get(option, option)


def concerned_documents(issue: PlannerIssue, answer: str | None) -> list[str]:
    """Document types an ask-at-the-office step is about: the wrong ones, when the family said which is right."""
    if issue.type in MISMATCHES and answer and answer != NOT_SURE:
        wrong = wrong_doc_types(issue, answer)
        if wrong:
            return [t for t in dict.fromkeys(issue.documents.values()) if t in wrong]
    return list(dict.fromkeys(issue.documents.values())) or [issue.document_type]


def step_voice(step: FixStep, issues: dict[str, PlannerIssue], answers: dict[str, str], language: str) -> str:
    """The sentence for one step. `answers`: issue id -> the family's answer to 'which is correct'."""
    t = load_voice(language)
    issue = next((issues[i] for i in step.issue_ids if i in issues), None)
    member = member_text(issue, language)
    if step.kind == "question":
        return question_text(issue, step.question_kind, language)
    if step.kind == "ask_at_office":
        docs = concerned_documents(issue, answers.get(issue.id)) if issue else []
        return t.ask_at_office.format(member=member, documents=document_names(docs, language))
    p = load_fixes()[step.procedure_id]
    return t.procedures[p.id].format(
        member=member,
        office=say(t, p.office) if step.office else "",
        bring="; ".join(say(t, f) for f in p.bring if f.value in step.bring),
        fee=say(t, p.fee) if step.fee else "",
        time_limit=say(t, p.time_limit) if step.time_limit else "",
        caution=" ".join(say(t, f) for f in p.cautions if f.value in step.cautions),
        documents=document_names(list(issue.documents.values()) if issue else [], language),
    )


def plan_voice(steps: list[FixStep], issues: list[PlannerIssue], language: str) -> list[str]:
    """Sentences for a whole plan in any language (the family's answers come from its question steps)."""
    by_id = {i.id: i for i in issues}
    answers = {s.issue_ids[0]: s.answer for s in steps
               if s.kind == "question" and s.question_kind == "which_is_correct" and s.answer}
    return [step_voice(s, by_id, answers, language) for s in steps]
