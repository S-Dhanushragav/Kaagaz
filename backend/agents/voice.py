"""Voice sentences for the fix plan, from templates in data/templates/voice/{en,hi,mr}.yaml.

No model writes these sentences. Each is a template filled from a verified plan step: every placeholder
value is a knowledge-base fact (shown in the language's wording), a member's name, or document display
names. A sentence with any unverified fact ends with the language's "please confirm this at the office".
Questions show documents by their display names (never internal ids) with the values that differ.
Document names are only ever a label ("{documents}: ..."), so no language needs an inflected form.
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
# Cautions that already tell the family to check at the office: no extra "confirm at the office" after them.
OFFICE_REFERRALS = frozenset({"Confirm at the office which documents are needed.",
                              "Acceptance of the declaration is up to the office."})


class NumberWords(BaseModel):
    """Words for spelling out numbers in speech (screen text keeps digits)."""

    model_config = ConfigDict(extra="forbid")

    words: list[str]  # 0-99
    hundreds: list[str]  # 100, 200, ... 900
    thousand: str
    century: str  # years 1100-1999, e.g. '{n} hundred' -> 'nineteen hundred eighty-one'
    months: list[str]
    rupees: str | None = None  # 'Rs 75' -> '{n} rupees' (English text only)


class AnswerWords(BaseModel):
    """Reading options aloud, and the only words a spoken answer is matched by (agents/answers.py)."""

    model_config = ConfigDict(extra="forbid")

    labels: list[str]  # option labels read aloud: First, Second, ...
    option: str  # "{label}: {option}."
    instruction: str
    retry: str
    buttons: str
    english_only: str | None = None  # hi/mr: the values differ only in Latin script: look at the screen
    numbers: list[list[str]]  # words meaning option 1, 2, ... (digits always count too)
    not_sure: list[str]


class VoiceTemplates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numbers: NumberWords
    answers: AnswerWords
    language: str
    documents: dict[str, str]  # document type -> display name
    values: dict[str, str] = {}  # knowledge-base value -> how it is said in this language
    unverified: str  # marker after an unverified fact
    household: str  # said when a step concerns the whole household
    not_on_card: str  # a person not on the ration card whose document gives no readable name
    card_member: str  # 'Member {n} on the ration card' (its name unreadable)
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
    return "" if fact is None else t.values.get(fact.value, fact.value)


def with_marker(t: VoiceTemplates, sentence: str, facts: list[Fact]) -> str:
    """Add 'please confirm this at the office' once, at the end, if any fact in the sentence is unverified
    (unless the sentence already sends the family to the office for it)."""
    if any(f.value in OFFICE_REFERRALS for f in facts) or all(f.status == "verified" for f in facts):
        return sentence
    return f"{sentence} {t.unverified}"


def member_text(issue: PlannerIssue | None, language: str) -> str:
    """The person a step is about: their name; without a readable name, 'a person not on the ration card' or
    'member N on the ration card'. 'Your family' only for steps about the whole household."""
    t = load_voice(language)
    if issue is None or issue.member_id is None:
        return t.household
    name = issue.member_name_mr if language != "en" and issue.member_name_mr else issue.member_name
    if name:
        return name
    if issue.member_id.startswith("r") and issue.member_id[1:].isdigit():
        return t.card_member.format(n=issue.member_id[1:])
    return t.not_on_card


def document_names(doc_types: list[str], language: str) -> str:
    t = load_voice(language)
    return ", ".join(dict.fromkeys(t.documents[x] for x in doc_types if x))


def _in_script(value: str, devanagari: bool) -> str | None:
    return next((p for p in value.split(" / ") if bool(DEVANAGARI.search(p)) == devanagari), None)


def shown_values(issue: PlannerIssue, language: str) -> dict[str, str]:
    """Each document's value in the script that shows the difference (the language's own script first)."""
    for dev in (language != "en", language == "en"):
        candidate = {d: _in_script(v, dev) for d, v in issue.values.items()}
        if all(candidate.values()) and len({comparison_key(v) for v in candidate.values()}) > 1:
            return candidate
    return dict(issue.values)


def shown_value(value: str, issue: PlannerIssue, language: str) -> str:
    """One of the issue's values (an option) as it is shown in this language."""
    shown = shown_values(issue, language)
    return next((shown[d] for d, v in issue.values.items() if v == value), value)


def english_only(issue: PlannerIssue, language: str) -> bool:
    """In Hindi or Marathi: the values differ only in Latin script, which these voices cannot say."""
    if language == "en" or not issue.values:
        return False
    return not any(DEVANAGARI.search(v) or not re.search(r"[A-Za-z]", v) for v in shown_values(issue, language).values())


def documents_with_values(issue: PlannerIssue, language: str) -> str:
    """'ration card: X; Aadhaar card: Y' (for the screen: both spellings)."""
    t = load_voice(language)
    groups: dict[str, list[str]] = {}
    for d, v in shown_values(issue, language).items():
        groups.setdefault(v, []).append(t.documents[issue.documents[d]])
    return "; ".join(f"{', '.join(dict.fromkeys(names))}: {v}" for v, names in groups.items())


def question_text(issue: PlannerIssue, kind: str, language: str) -> str:
    """The question names the documents only; the numbered options carry the values."""
    t = load_voice(language)
    return t.questions[kind].format(member=member_text(issue, language),
                                    documents=document_names(list(issue.documents.values()), language))


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
    template = t.procedures[p.id]
    bring = [f for f in p.bring if f.value in step.bring]
    cautions = [f for f in p.cautions if f.value in step.cautions]
    sentence = template.format(
        member=member,
        office=say(t, p.office) if step.office else "",
        bring="; ".join(say(t, f) for f in bring),
        fee=say(t, p.fee) if step.fee else "",
        time_limit=say(t, p.time_limit) if step.time_limit else "",
        caution=" ".join(say(t, f) for f in cautions),
        documents=document_names(list(issue.documents.values()) if issue else [], language),
    )
    spoken = [f for name, f in (("office", p.office if step.office else None), ("fee", p.fee if step.fee else None),
                                ("time_limit", p.time_limit if step.time_limit else None)) if f and f"{{{name}}}" in template]
    spoken += (bring if "{bring}" in template else []) + (cautions if "{caution}" in template else [])
    return with_marker(t, sentence, spoken)


def plan_voice(steps: list[FixStep], issues: list[PlannerIssue], language: str) -> list[str]:
    """Sentences for a whole plan in any language (the family's answers come from its question steps)."""
    by_id = {i.id: i for i in issues}
    answers = {s.issue_ids[0]: s.answer for s in steps
               if s.kind == "question" and s.question_kind == "which_is_correct" and s.answer}
    return [step_voice(s, by_id, answers, language) for s in steps]
