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


def full(record: CheckRecord, previous: CheckRecord | None = None) -> dict[str, Any]:
    """One check in full; after "Check again", with what changed since the check it re-checked."""
    return {**summary(record), "data": record.data.model_dump(mode="json"),
            "steps_done": {str(k): v for k, v in record.steps_done.items()},
            "comparison": {"previous_created": previous.created.isoformat(), **compare(previous.data, record.data)}
            if previous is not None else None}


# ---------- re-check: what changed since the last check ----------

def _name_key(name_en: str | None, name_mr: str | None) -> str:
    """Names compared case- and space-insensitively (English first: both checks read the same printed names)."""
    return " ".join((name_en or name_mr or "").casefold().split())


def _same_problem(a: StoredProblem, b: StoredProblem) -> bool:
    if a.type != b.type or _name_key(a.member_name, a.member_name_mr) != _name_key(b.member_name, b.member_name_mr):
        return False
    return not (a.document_types or b.document_types) or bool(set(a.document_types) & set(b.document_types))


def compare(previous: CheckData, current: CheckData) -> dict[str, Any]:
    """Problems fixed / still open / new (matched by type, member name and document type), and scheme outcomes
    that changed for the same person (matched by name)."""
    unmatched = list(current.problems)
    fixed, still = [], []
    for p in previous.problems:
        match = next((c for c in unmatched if _same_problem(p, c)), None)
        if match is None:
            fixed.append(p)
        else:
            unmatched.remove(match)
            still.append(match)

    def by_person(data: CheckData) -> dict[tuple[str, str], tuple[StoredMember, StoredOutcome]]:
        members = {m.member_id: m for m in data.members}
        out = {}
        for o in data.outcomes:
            m = members.get(o.member_id)
            if m is not None:
                out[(_name_key(m.name_en, m.name_mr), o.scheme_id)] = (m, o)
        return out

    before, after = by_person(previous), by_person(current)
    changed = []
    for key, (m, o) in after.items():
        old = before.get(key)
        if old is not None and old[1].outcome != o.outcome:
            changed.append({"member_name": m.name_en, "member_name_mr": m.name_mr, "scheme_id": o.scheme_id,
                            "before": old[1].outcome, "after": o.outcome})
    dump = lambda ps: [p.model_dump(mode="json") for p in ps]  # noqa: E731
    return {"fixed": dump(fixed), "still_open": dump(still), "new": dump(unmatched), "outcomes_changed": changed}
