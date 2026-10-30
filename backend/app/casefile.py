"""The family's case file: what is kept from a finished check, and summaries for the history list.

`check_data` copies only allow-listed fields from a session view into storage.models.CheckData: names, relations,
ages, document *types*, problems, scheme outcomes with their reasons, plan steps and the family's answers. Images,
crops, video, evidence values and ID numbers are never copied; every text is also passed through the ID-number
redactor in case one ever appears in a sentence.
"""

from typing import Any

from storage.models import (CheckData, CheckRecord, StoredAnswer, StoredFact, StoredMember, StoredOutcome,
                            StoredProblem, StoredStep)
from vision.text import redact_identity_numbers

STOP_MODES = ("sweep_again", "no_documents")  # nothing is built on these reads: nothing to keep


def _t(text: Any) -> str | None:
    return redact_identity_numbers(str(text)) if text is not None else None


def _fact(shown: dict[str, Any] | None) -> StoredFact | None:
    return StoredFact(text=_t(shown["text"]) or "", verified=bool(shown.get("verified"))) if shown else None


def worth_keeping(view: dict[str, Any]) -> bool:
    """A finished run with results (not stopped for a new sweep). The caller knows the run has finished."""
    return bool(view.get("household")) and (view.get("recapture") or {}).get("mode") not in STOP_MODES


def check_data(view: dict[str, Any]) -> CheckData:
    hh = view.get("household") or {}
    doc_types = {d: (x or {}).get("doc_type") for d, x in (hh.get("documents") or {}).items()}
    members = [StoredMember(member_id=m["member_id"], name_mr=_t(m.get("name_mr")), name_en=_t(m.get("name_en")),
                            relation_en=_t(m.get("relation_en")), age=m.get("age"),
                            on_ration_card=bool(m.get("on_ration_card"))) for m in hh.get("members", [])]
    names = {m.member_id: (m.name_en, m.name_mr) for m in members}

    def problem(i: dict[str, Any], waiting: bool) -> StoredProblem:
        types = sorted({t for t in (i.get("documents") or {}).values() if t})
        if i.get("document_type") and i["type"] == "missing_document":
            types = [i["document_type"]]
        en, mr = names.get(i.get("member_id"), (None, None))
        return StoredProblem(type=i["type"], member_id=i.get("member_id"),
                             member_name=_t(i.get("member_name") or en), member_name_mr=_t(i.get("member_name_mr") or mr),
                             document_types=types, waiting=waiting)

    problems = [problem(i, False) for i in view.get("issues") or []]
    problems += [problem(i, True) for i in view.get("waiting") or []]
    for i in hh.get("issues", []):
        if i.get("type") == "unreadable" and i.get("severity") != "info":
            problems.append(StoredProblem(type="unreadable", member_id=None, member_name=None, member_name_mr=None,
                                          document_types=sorted({doc_types.get(d) for d in i.get("documents", [])
                                                                 if doc_types.get(d)}), waiting=False))

    outcomes = [StoredOutcome(member_id=r["member_id"], scheme_id=r["scheme_id"], outcome=r["outcome"],
                              reasons=[_t(x) or "" for x in (r.get("display") or {}).get("reasons", r.get("reasons", []))],
                              warnings=[_t(x) or "" for x in (r.get("display") or {}).get("warnings", [])])
                for r in view.get("results") or []]

    plan = (view.get("plan") or {}).get("steps", [])
    speech = view.get("speech") or []
    steps, answers = [], []
    for i, s in enumerate(plan):
        if s.get("kind") == "question":
            if s.get("question") and s.get("answer"):
                answers.append(StoredAnswer(question=_t(s["question"]) or "", answer=_t(s["answer"]) or ""))
            continue
        said = speech[i] if i < len(speech) else {}
        display = said.get("display") or {}
        steps.append(StoredStep(index=i, kind=s["kind"], visit=s.get("visit"), office=_fact(display.get("office")),
                                voice=_t(s.get("voice")) or "", speech=_t(said.get("speech") or s.get("voice")) or "",
                                bring=[f for f in (_fact(b) for b in display.get("bring", [])) if f],
                                fee=_fact(display.get("fee")), time_limit=_fact(display.get("time_limit")),
                                member_id=s.get("member_id")))
    return CheckData(members=members, documents=sorted(t for t in doc_types.values() if t), problems=problems,
                     outcomes=outcomes, steps=steps, answers=answers)


def open_steps(record: CheckRecord) -> list[int]:
    return [s.index for s in record.data.steps if not record.steps_done.get(s.index)]


def summary(record: CheckRecord) -> dict[str, Any]:
    """One line of the history list: date, the head of the family, problems, open steps and visits."""
    members = record.data.members
    head = next((m for m in members if m.member_id == "r1"), members[0] if members else None)
    still = set(open_steps(record))
    return {
        "id": record.id, "created": record.created.isoformat(), "language": record.language,
        "previous_id": record.previous_id,
        "head": {"name_en": head.name_en, "name_mr": head.name_mr} if head else None,
        "problems": len(record.data.problems), "steps": len(record.data.steps), "open_steps": len(still),
        "open_visits": len({s.visit for s in record.data.steps if s.index in still and s.visit}),
    }


def full(record: CheckRecord) -> dict[str, Any]:
    return {**summary(record), "data": record.data.model_dump(mode="json"),
            "steps_done": {str(k): v for k, v in record.steps_done.items()}}
