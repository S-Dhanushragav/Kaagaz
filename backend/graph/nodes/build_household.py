"""Household builder: document extractions -> members, links, and issues.

Plain function for now; it becomes a LangGraph node later. Deterministic, except for borderline
name scores (70-90), where the text model is asked whether two records are the same person and its
reason is logged. Steps:
1. unreadable documents -> 'unreadable' issues (recapture)
2. duplicate identity cards (same ID last 4 + same date of birth) are merged
3. the ration card's member list defines the household
4. every other document is linked to a member by name score (>= 90 link; 70-90 ask the model;
   < 70 no link). Two members within 5 points: date of birth and gender break the tie.
   Secondary link: a score of 50-70 still goes to the model if the document's age (from its date of
   birth, within 1 year) and gender fit exactly one member without a document of that type.
   Unlinked documents belong to people not on the ration card.
5. separate exact checks per member: names (per script, after normalization) and dates of birth.
   A null value is never a mismatch. With a name verifier, every document in a name mismatch is
   re-read (name only, closer look); the mismatch is reported only if the re-read still differs.
6. missing documents: an identity card for every adult on the ration card (a child's is an info
   note) and one income certificate per household; old income certificates get a warning.
"""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from openai import APIError
from pydantic import BaseModel, ValidationError

from clients.llm import LLMError, TokenUsage, complete
from matching.names import NamePair, name_score
from rules.engine import financial_year_start
from rules.loader import load_shared
from schemas.documents import DECISION_FIELDS, DocumentExtraction, field_pattern, null_paths
from schemas.household import Household, HouseholdMember, LinkDecision
from schemas.issues import Issue
from vision.text import comparison_key, normalize_text, redact_identity_numbers

MATCH, ASK, SECONDARY, TIE_MARGIN = 90.0, 70.0, 50.0, 5.0
LINKED_TYPES = ("identity_card", "caste_certificate", "income_certificate")
PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
PROMPT = (PROMPTS / "name_adjudicator.md").read_text(encoding="utf-8")
VERIFY_PROMPT = (PROMPTS / "verify_name.md").read_text(encoding="utf-8")
VERIFY_EFFORT = "medium"
_NULLABLE = {"anyOf": [{"type": "string"}, {"type": "null"}]}
VERIFY_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {"name": "name_read", "strict": True, "schema": {
        "type": "object", "properties": {"name_mr": _NULLABLE, "name_en": _NULLABLE},
        "required": ["name_mr", "name_en"], "additionalProperties": False}},
}


class Adjudication(BaseModel):
    same_person: bool
    reason: str
    usage: TokenUsage = TokenUsage()


Adjudicator = Callable[[dict[str, Any], dict[str, Any]], Adjudication]


class NameQuery(BaseModel):
    """Which name to re-read: the holder's, or one ration-card member row (1-based)."""

    document_id: str
    doc_type: str
    row: int | None = None
    relation: str | None = None


class NameRead(BaseModel):
    name_mr: str | None = None
    name_en: str | None = None
    error: str | None = None
    usage: TokenUsage = TokenUsage()


NameVerifier = Callable[[NameQuery], NameRead]


def llm_adjudicator(reference_date: date, llm: Callable[..., Any] = complete) -> Adjudicator:
    """Ask the text model (Muse Spark Open on Baseten) whether two name records are the same person."""

    def run(doc: dict[str, Any], member: dict[str, Any]) -> Adjudication:
        values = {**{f"a_{k}": v for k, v in doc.items()}, **{f"b_{k}": v for k, v in member.items()},
                  "reference_date": f"{reference_date:%d/%m/%Y}"}
        prompt = PROMPT
        for key, value in values.items():
            prompt = prompt.replace("{" + key + "}", "unknown" if value is None else str(value))
        try:
            resp = llm(prompt, task="text")
        except (LLMError, APIError) as e:
            return Adjudication(same_person=False, reason=f"adjudicator call failed: {e}")
        text = resp.text
        start, end = text.find("{"), text.rfind("}")
        try:
            return Adjudication.model_validate({**json.loads(text[start : end + 1]), "usage": resp.usage})
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
            return Adjudication(same_person=False, reason=f"adjudicator reply not valid JSON: {text[:120]!r}",
                                usage=resp.usage)

    return run


def llm_name_verifier(images: Mapping[str, Sequence[bytes]], *, overrides: Mapping[str, Any] | None = None,
                      llm: Callable[..., Any] = complete) -> NameVerifier:
    """Re-read one name from a document's images (vision model, reasoning effort medium).

    `images`: document id -> its prepared images (the same crops the reader saw).
    """
    settings = {"reasoning_effort": VERIFY_EFFORT, **(overrides or {})}

    def run(q: NameQuery) -> NameRead:
        if q.document_id not in images:
            return NameRead(error="no image for this document")
        if q.row is not None:
            which = f"member number {q.row} in the members table, counting from the top"
            which += f" (relation to the head of family: {q.relation})" if q.relation else ""
        else:
            which = "the name of the person this document is issued to"
        prompt = VERIFY_PROMPT.replace("{doc_type}", q.doc_type.replace("_", " ")).replace("{which}", which)
        try:
            resp = llm(prompt, task="vision", images=list(images[q.document_id]),
                       response_format=VERIFY_RESPONSE_FORMAT, overrides=settings, redact=redact_identity_numbers)
        except (LLMError, APIError) as e:
            return NameRead(error=f"verification call failed: {e}")
        start, end = resp.text.find("{"), resp.text.rfind("}")
        try:
            data = json.loads(resp.text[start : end + 1])
            clean = {k: (normalize_text(data[k]).strip() or None) if isinstance(data.get(k), str) else None
                     for k in ("name_mr", "name_en")}
            return NameRead(**clean, usage=resp.usage)
        except (json.JSONDecodeError, ValidationError, ValueError, AttributeError, TypeError):
            return NameRead(error=f"verification reply not valid JSON: {resp.text[:120]!r}", usage=resp.usage)

    return run


# ---------- small helpers ----------

def _gender(fields: Any) -> str | None:
    en = (getattr(fields, "gender_en", None) or "").strip().lower()
    mr = (getattr(fields, "gender_mr", None) or "").strip()
    if en.startswith("f") or mr == "स्त्री":
        return "F"
    if en.startswith("m") or mr == "पुरुष":
        return "M"
    return None


def _date(value: str | None) -> date | None:
    try:
        return datetime.strptime(value, "%d/%m/%Y").date() if value else None
    except ValueError:
        return None


def _age(dob: date, ref: date) -> int:
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))


def _names(fields: Any) -> NamePair:
    return NamePair(getattr(fields, "name_mr", None), getattr(fields, "name_en", None))


def _issue(kind: str, severity: str, member: str | None, docs: list[str], message: str, **evidence: Any) -> Issue:
    return Issue(type=kind, severity=severity, member_id=member, documents=docs, evidence=evidence, message=message)


# ---------- linking ----------

def _tiebreak(doc: DocumentExtraction, close: list[tuple[float, HouseholdMember]], ref: date) -> tuple[float, HouseholdMember, str]:
    """Among members within 5 points: prefer the one whose gender and age fit the document."""
    gender, dob = _gender(doc.fields), _date(getattr(doc.fields, "dob", None))
    age = _age(dob, ref) if dob else None

    def fit(m: HouseholdMember) -> int:
        points = 0
        if gender and m.gender:
            points += 1 if gender == m.gender else -1
        if age is not None and m.age is not None:
            points += 1 if abs(age - m.age) <= 1 else -1
        return points

    score, member = max(close, key=lambda c: (fit(c[1]), c[0]))
    others = ", ".join(f"{m.member_id} ({s})" for s, m in close if m is not member)
    return score, member, f"tie with {others}; chose {member.member_id} by gender/age fit ({fit(member)})"


def _ask(doc: DocumentExtraction, member: HouseholdMember, adjudicate: Adjudicator) -> Adjudication:
    return adjudicate(
        {"doc_type": doc.doc_type.replace("_", " "), "mr": getattr(doc.fields, "name_mr", None),
         "en": getattr(doc.fields, "name_en", None), "dob": getattr(doc.fields, "dob", None),
         "gender": _gender(doc.fields)},
        {"mr": member.name_mr, "en": member.name_en, "age": member.age, "gender": member.gender,
         "relation": member.relation_en},
    )


def _secondary(doc: DocumentExtraction, candidates: list[tuple[float, HouseholdMember]],
               ref: date) -> tuple[float, HouseholdMember] | None:
    """The one free member whose age (within 1 year) and gender fit the document, if its name score >= 50."""
    gender, dob = _gender(doc.fields), _date(getattr(doc.fields, "dob", None))
    if gender is None or dob is None:
        return None
    age = _age(dob, ref)
    fits = [(s, m) for s, m in candidates if m.gender == gender and m.age is not None and abs(m.age - age) <= 1]
    return fits[0] if len(fits) == 1 and fits[0][0] >= SECONDARY else None


def _link(doc: DocumentExtraction, candidates: list[tuple[float, HouseholdMember]], ref: date,
          adjudicate: Adjudicator | None) -> tuple[HouseholdMember | None, LinkDecision, Adjudication | None]:
    """Returns (member or None, decision, the model's verdict if it was asked).

    `candidates` are the members without a document of this type yet, best name score first.
    """
    if not candidates or candidates[0][0] < ASK:
        best = candidates[0][0] if candidates else 0.0
        fit = _secondary(doc, candidates, ref) if adjudicate is not None and best >= SECONDARY else None
        if fit is None:
            return None, LinkDecision(document_id=doc.document_id, member_id=None, score=best, method="none",
                                      reason=f"best name score {best} < {ASK}"), None
        score, member = fit
        verdict = _ask(doc, member, adjudicate)
        decision = LinkDecision(
            document_id=doc.document_id, member_id=member.member_id if verdict.same_person else None, score=score,
            method="llm", reason=f"secondary: name score {score}, the only free member whose age and gender fit; "
                                 f"model: {verdict.reason}")
        return (member if verdict.same_person else None), decision, verdict
    score, member = candidates[0]
    method, reason = "fuzzy", f"name score {score}"
    close = [c for c in candidates if c[0] >= score - TIE_MARGIN and c[0] >= ASK]
    if len(close) > 1:
        score, member, reason = _tiebreak(doc, close, ref)
        method = "tiebreak"
    if score >= MATCH:
        return member, LinkDecision(document_id=doc.document_id, member_id=member.member_id, score=score,
                                    method=method, reason=reason), None
    if adjudicate is None:
        return None, LinkDecision(document_id=doc.document_id, member_id=None, score=score, method="none",
                                  reason=f"borderline score {score}; no adjudicator"), None
    verdict = _ask(doc, member, adjudicate)
    decision = LinkDecision(document_id=doc.document_id, member_id=member.member_id if verdict.same_person else None,
                            score=score, method="llm", reason=f"model: {verdict.reason}")
    return (member if verdict.same_person else None), decision, verdict


# ---------- builder ----------

def _name_differences(records: dict[str, NamePair]) -> dict[str, dict[str, str]]:
    """Per script, the documents' names if they don't all agree (nulls ignored)."""
    differing: dict[str, dict[str, str]] = {}
    for script in ("mr", "en"):
        values = {d: getattr(n, script) for d, n in records.items() if getattr(n, script)}
        if len({comparison_key(v) for v in values.values()}) > 1:
            differing[script] = values
    return differing


def build_household(
    extractions: list[DocumentExtraction], reference_date: date, *, adjudicate: Adjudicator | None = None,
    verify: NameVerifier | None = None,
) -> Household:
    issues: list[Issue] = []
    links: list[LinkDecision] = []
    llm_calls = verification_calls = 0
    usage = TokenUsage()

    def add_usage(u: TokenUsage) -> None:
        usage.prompt_tokens += u.prompt_tokens
        usage.completion_tokens += u.completion_tokens
        usage.total_tokens += u.total_tokens

    # 1. Unreadable documents.
    usable = []
    for ex in extractions:
        if ex.doc_type == "other":
            continue
        if ex.unreadable or ex.fields is None or ex.doc_type is None:
            issues.append(_issue("unreadable", "blocker", None, [ex.document_id],
                                 "This document could not be read: take a clearer photo of it.",
                                 error=ex.error, retake_reasons=ex.retake_reasons))
            continue
        usable.append(ex)

    # 2. Duplicate identity cards (same ID last 4 and same date of birth): keep the more complete one.
    kept: list[DocumentExtraction] = []
    seen: dict[tuple[str, str], int] = {}
    for ex in usable:
        key = (getattr(ex.fields, "id_number", None), getattr(ex.fields, "dob", None))
        if ex.doc_type == "identity_card" and all(key):
            if key in seen:
                first = kept[seen[key]]
                keep, drop = (ex, first) if len(list(null_paths(ex.fields))) < len(list(null_paths(first.fields))) else (first, ex)
                kept[seen[key]] = keep
                issues.append(_issue("duplicate_merged", "info", None, [keep.document_id, drop.document_id],
                                     "The same identity card was captured twice; merged.",
                                     id_number=key[0], dob=key[1], kept=keep.document_id))
                continue
            seen[key] = len(kept)
        kept.append(ex)
    docs = {ex.document_id: ex for ex in kept}

    # 3. Members from the ration card.
    cards = [ex for ex in kept if ex.doc_type == "ration_card"]
    card = cards[0] if cards else None
    members: list[HouseholdMember] = []
    if card is None:
        issues.append(_issue("missing_document", "blocker", None, [], "No ration card was found.",
                             document_type="ration_card"))
    else:
        for i, row in enumerate(card.fields.members, 1):
            members.append(HouseholdMember(
                member_id=f"r{i}", on_ration_card=True, name_mr=row.name_mr, name_en=row.name_en,
                relation_en=row.relation_en, gender=_gender(row), age=row.age,
                age_source="ration_card" if row.age is not None else None,
            ))

    # 4. Link documents to members; clearest matches first so they claim their member first.
    to_link = [ex for ex in kept if ex.doc_type in LINKED_TYPES]

    def ranked(ex: DocumentExtraction, pool: list[HouseholdMember]) -> list[tuple[float, HouseholdMember]]:
        return sorted(((name_score(_names(ex.fields), NamePair(m.name_mr, m.name_en)), m) for m in pool),
                      key=lambda c: c[0], reverse=True)

    to_link.sort(key=lambda ex: -(ranked(ex, members)[0][0] if members else 0.0))
    extras: list[HouseholdMember] = []
    for ex in to_link:
        free = [m for m in members if not m.documents.get(ex.doc_type)]  # one document of each type per member
        member, decision, verdict = _link(ex, ranked(ex, free), reference_date, adjudicate)
        if verdict is not None:
            llm_calls += 1
            add_usage(verdict.usage)
        links.append(decision)
        if member is None:  # someone not on the ration card: group their documents together
            same = [x for x in extras if name_score(_names(ex.fields), NamePair(x.name_mr, x.name_en)) >= MATCH
                    and not x.documents.get(ex.doc_type)]
            if same:
                member = same[0]
            else:
                member = HouseholdMember(member_id=f"x{len(extras) + 1}", on_ration_card=False,
                                         name_mr=getattr(ex.fields, "name_mr", None),
                                         name_en=getattr(ex.fields, "name_en", None), gender=_gender(ex.fields))
                extras.append(member)
        member.documents.setdefault(ex.doc_type, []).append(ex.document_id)

    # Member details: date of birth and age from the identity card; otherwise the ration card's age.
    for m in members + extras:
        id_doc = next((docs[d] for d in m.documents.get("identity_card", [])), None)
        dob_docs = [docs[d] for t in ("identity_card", "caste_certificate") for d in m.documents.get(t, [])]
        dob = _date(getattr(id_doc.fields, "dob", None)) if id_doc else None
        dob = dob or next((_date(d.fields.dob) for d in dob_docs if _date(d.fields.dob)), None)
        if dob:
            m.dob, m.age, m.age_source = dob, _age(dob, reference_date), "identity_card"
        if m.gender is None and id_doc:
            m.gender = _gender(id_doc.fields)

    # 5. Exact checks per member: names (per script) and dates of birth. Nulls never count.
    for m in members + extras:
        records: dict[str, NamePair] = {}
        if m.on_ration_card and card:
            records[card.document_id] = NamePair(m.name_mr, m.name_en)
        for t in LINKED_TYPES:
            for d in m.documents.get(t, []):
                records[d] = _names(docs[d].fields)
        differing = _name_differences(records)
        if differing and verify is not None:
            reads: dict[str, NameRead] = {}
            for d in sorted({d for values in differing.values() for d in values}):
                row = int(m.member_id[1:]) if card and d == card.document_id else None
                reads[d] = verify(NameQuery(document_id=d, doc_type=docs[d].doc_type, row=row,
                                            relation=m.relation_en if row else None))
                verification_calls += 1
                add_usage(reads[d].usage)
            # A script the re-read couldn't read keeps the first read, so a failed check never hides a mismatch.
            reread = {d: NamePair(reads[d].name_mr or n.mr, reads[d].name_en or n.en) if d in reads else n
                      for d, n in records.items()}
            confirmed = {s: v for s, v in _name_differences(reread).items() if s in differing}
            verification = {d: {"first_read": {"mr": records[d].mr, "en": records[d].en},
                                "re_read": {"mr": r.name_mr, "en": r.name_en}, **({"error": r.error} if r.error else {})}
                            for d, r in reads.items()}
            if confirmed:
                involved = sorted({d for values in confirmed.values() for d in values})
                issues.append(_issue("name_mismatch", "blocker", m.member_id, involved,
                                     "The name is spelled differently on these documents.", names=confirmed,
                                     first_read_names=differing, verification=verification))
            else:
                issues.append(_issue("name_verified", "info", m.member_id, sorted(reads),
                                     "A spelling difference was not confirmed on a closer second read.",
                                     first_read_names=differing, verification=verification))
        elif differing:
            involved = sorted({d for values in differing.values() for d in values})
            issues.append(_issue("name_mismatch", "blocker", m.member_id, involved,
                                 "The name is spelled differently on these documents.", names=differing))
        dobs = {d: docs[d].fields.dob for t in ("identity_card", "caste_certificate")
                for d in m.documents.get(t, []) if docs[d].fields.dob}
        if len(set(dobs.values())) > 1:
            issues.append(_issue("dob_mismatch", "blocker", m.member_id, sorted(dobs),
                                 "The date of birth differs between these documents.", dates_of_birth=dobs))

    for x in extras:
        issues.append(_issue("not_on_ration_card", "blocker", x.member_id,
                             [d for ds in x.documents.values() for d in ds],
                             "These documents belong to someone who is not on the ration card.",
                             name_mr=x.name_mr, name_en=x.name_en))

    # 6. Missing documents and old income certificates.
    for m in members:
        if m.documents.get("identity_card"):
            continue
        if m.age is not None and m.age >= 18:
            issues.append(_issue("missing_document", "blocker", m.member_id, [],
                                 f"No identity card for {m.name_en or m.member_id} (adult).",
                                 document_type="identity_card", age=m.age, age_source=m.age_source))
        else:
            issues.append(_issue("missing_document", "info", m.member_id, [],
                                 f"No identity card for {m.name_en or m.member_id} (child or age unknown).",
                                 document_type="identity_card", age=m.age))
    incomes = [ex for ex in kept if ex.doc_type == "income_certificate"]
    if not incomes:
        issues.append(_issue("missing_document", "blocker", None, [], "No income certificate for the household.",
                             document_type="income_certificate"))
    income = max(incomes, key=lambda ex: _date(ex.fields.issue_date) or date.min) if incomes else None
    validity = load_shared().rule("income_certificate_validity")
    fy_start = financial_year_start(reference_date)
    for ex in incomes:
        issued = _date(ex.fields.issue_date)
        if issued and issued < fy_start:
            holder = next((m.member_id for m in members + extras
                           if ex.document_id in m.documents.get("income_certificate", [])), None)
            issues.append(_issue("expired", "warning", holder, [ex.document_id],
                                 f"Income certificate issued {ex.fields.issue_date}: {validity.value['message']}.",
                                 issue_date=ex.fields.issue_date, financial_year_start=f"{fy_start:%d/%m/%Y}",
                                 rule_status=validity.status))

    # Unreadable fields that decisions need (and documents the reader flagged for a retake).
    owner = {d: m.member_id for m in members + extras for ds in m.documents.values() for d in ds}
    for ex in kept:
        needed = [p for p in null_paths(ex.fields) if field_pattern(p) in DECISION_FIELDS[ex.doc_type]]
        if needed or ex.needs_retake:
            issues.append(_issue("unreadable", "blocker", owner.get(ex.document_id), [ex.document_id],
                                 "Some details could not be read: take a close-up photo of this document.",
                                 fields=needed, retake_reasons=ex.retake_reasons))

    return Household(
        reference_date=reference_date,
        ration_card_id=card.document_id if card else None,
        card_colour=card.fields.card_colour if card else None,
        members=members + extras,
        documents=docs,
        income_document_id=income.document_id if income else None,
        issues=issues,
        links=links,
        llm_calls=llm_calls,
        verification_calls=verification_calls,
        usage=usage,
    )
