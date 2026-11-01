"""Ask Kaagaz: what the agent can look up (read-only), action chips and suggested questions. Deterministic.

Scheme facts come only from data/schemes (rules/loader.py, worded by agents/catalog.py); office and procedure facts
only from data/fixes (agents/tools.py); a family's facts only from its check (a live session view or a saved check,
both reduced to a FamilyContext). No tool writes anything or reaches the internet.

Text read from documents (names, relations) is untrusted: it is passed only in fields whose names end in
`_from_document`, and the prompt tells the model those are data, never instructions.
Chips ("Add a photo: Savita: Aadhaar card") are built here from the check; the model only picks chip ids that a tool
returned, and the answer keeps only those (agents/ask.py).
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from agents.catalog import scheme_card
from agents.tools import load_fixes
from agents.voice import load_voice
from rules.loader import Scheme, load_schemes
from storage.models import CheckData, CheckRecord, StoredFact
from vision.text import comparison_key

ASK_DIR = Path(__file__).resolve().parents[2] / "data" / "templates" / "ask"
NAME_LIMIT = 60  # characters of a name read from a document passed to the model

OUTCOME_MEANING = {
    "eligible_on_documents": "eligible on these documents (only the office decides)",
    "not_eligible": "not eligible: a rule fails",
    "blocked_by_issues": "not decided yet: a document problem must be fixed first",
    "check_at_office": "not decided: sources disagree, check at the office",
}
PROBLEM_MEANING = {
    "name_mismatch": "the name is spelled differently on these documents; which one to correct is in get_plan",
    "dob_mismatch": "the date of birth differs between these documents; which one to correct is in get_plan",
    "not_on_ration_card": "this person is not on the ration card",
    "missing_document": "this document was not found",
    "expired": "the income certificate may be too old and may need renewal (check at the office)",
    "unreadable": "the document could not be read clearly: a clearer photo is needed",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AskTemplates(_Strict):
    language: str
    brand: str  # the app's name as the UI spells it in this language
    brand_wrong: list[str] = []  # regexes: other ways of naming the app that an answer must not use
    replies: dict[str, str]
    lines: dict[str, str]
    chips: dict[str, str]
    suggestions: dict[str, str]


@lru_cache
def load_ask(language: str) -> AskTemplates:
    t = AskTemplates.model_validate(yaml.safe_load((ASK_DIR / f"{language}.yaml").read_text(encoding="utf-8")))
    if t.language != language:
        raise ValueError(f"{language}.yaml says language {t.language!r}")
    return t


# ---------- a family's check, live or saved ----------

class UnclearDocument(_Strict):
    document_id: str | None  # live checks: the document waiting for a close-up (None: saved checks)
    document_type: str | None  # None: not identified
    member_id: str | None


class FamilyContext(_Strict):
    """What Ask Kaagaz knows about one family: the allow-listed case-file data (storage.models.CheckData, ID numbers
    already redacted), plus, for a live check, the documents waiting for a clearer photo (for close-up chips)."""

    source: Literal["session", "saved_check"]
    language: str  # the check's language (reasons and plan sentences are in it)
    data: CheckData
    member_documents: dict[str, list[str]] = {}  # live checks: member id -> document types linked to them
    unclear: list[UnclearDocument] = []

    @classmethod
    def from_view(cls, view: dict[str, Any]) -> "FamilyContext":
        from app.casefile import check_data, document_owner

        data = check_data(view)
        hh = view.get("household") or {}
        docs = {m["member_id"]: sorted(m.get("documents") or {}) for m in hh.get("members", [])}
        recapture = view.get("recapture") or {}
        types = {e["document_id"]: (None if e.get("unreadable") else e.get("doc_type"))
                 for e in view.get("extractions") or []}
        unclear = [UnclearDocument(document_id=d, document_type=types.get(d), member_id=document_owner(view, d)[0])
                   for d in recapture.get("documents", [])]
        unclear += [UnclearDocument(document_id=d, document_type=None, member_id=None)
                    for d in recapture.get("unidentified", [])]
        return cls(source="session", language=view.get("language", "en"), data=data, member_documents=docs,
                   unclear=unclear)

    @classmethod
    def from_check(cls, record: CheckRecord) -> "FamilyContext":
        unclear = [UnclearDocument(document_id=None, document_type=t, member_id=p.member_id)
                   for p in record.data.problems if p.type == "unreadable" or p.waiting for t in p.document_types or [None]]
        return cls(source="saved_check", language=record.language, data=record.data, unclear=unclear)


# ---------- wording helpers ----------

def _clip(text: str | None) -> str | None:
    return None if text is None else " ".join(str(text).split())[:NAME_LIMIT]


def member_name(ctx: FamilyContext, member_id: str | None, language: str) -> str | None:
    m = next((m for m in ctx.data.members if m.member_id == member_id), None)
    if m is None:
        return None
    return _clip((m.name_en or m.name_mr) if language == "en" else (m.name_mr or m.name_en))


def document_name(doc_type: str | None, language: str) -> str:
    docs = load_voice(language).documents
    return docs.get(doc_type or "", {"en": "document", "hi": "दस्तावेज़", "mr": "कागदपत्र"}[language])


def scheme_short(scheme_id: str, language: str) -> str:
    s = next((s for s in load_schemes() if s.id == scheme_id), None)
    return (s.short.get(language) or s.short["en"]) if s else scheme_id


def find_scheme(name: str) -> Scheme | None:
    """A scheme by id, or by any of its names (any language, any spacing or case)."""
    key = comparison_key(name.replace("_", " "))
    for s in load_schemes():
        keys = {comparison_key(s.id.replace("_", " ")), *(comparison_key(v) for v in [*s.name.values(), *s.short.values()])}
        if key in keys or any(k and (k in key or key in k) for k in keys if len(key) >= 4):
            return s
    return None


def _fact(f: StoredFact | None) -> dict[str, Any] | None:
    return None if f is None else {"text": f.text, "verified": f.verified}


# ---------- chips ----------

class Chip(_Strict):
    id: str
    kind: Literal["closeup", "add_photos"]  # closeup: Take photo / Upload for a waiting document; add_photos: a new check
    document_id: str | None = None
    document_type: str | None = None
    member_id: str | None = None
    label: str


def chip_for(ctx: FamilyContext, document_type: str | None, member_id: str | None, document_id: str | None,
             language: str) -> Chip:
    t = load_ask(language)
    doc = document_name(document_type, language) if document_type else t.chips["unknown"]
    who = member_name(ctx, member_id, language)
    label = t.chips["photo"].format(document=t.chips["document_of"].format(member=who, document=doc) if who else doc)
    if document_id is not None:
        return Chip(id=f"photo:{document_id}", kind="closeup", document_id=document_id, document_type=document_type,
                    member_id=member_id, label=label)
    return Chip(id=f"add:{document_type or 'document'}:{member_id or '-'}", kind="add_photos",
                document_type=document_type, member_id=member_id, label=label)


# ---------- the tools ----------

class AskToolBox:
    """The read-only tools for one question. Every result is kept (`used`): the fact check compares the answer with
    them, and chips and sources come from them."""

    def __init__(self, language: str, ctx: FamilyContext | None = None) -> None:
        self.language = language
        self.ctx = ctx
        self.used: list[dict[str, Any]] = []  # {"tool", "args", "result"}
        self.chips: dict[str, Chip] = {}

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return SCHEME_TOOLS + (FAMILY_TOOLS if self.ctx is not None else [])

    def call(self, name: str, arguments: str) -> dict[str, Any]:
        allowed = {s["function"]["name"] for s in self.schemas}
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            result: dict[str, Any] = {"error": f"arguments are not valid: {e}"}
        else:
            if name not in allowed:
                result = {"error": f"unknown tool {name!r}"}
            else:
                before = set(self.chips)
                try:
                    result = getattr(self, f"_{name}")(**args)
                except TypeError as e:
                    result = {"error": f"bad arguments for {name}: {e}"}
                new = [c for c in self.chips.values() if c.id not in before]
                if new:  # listed once, up front, so the model sees which buttons it may offer
                    result = {"chips_available": [{"chip_id": c.id, "document_type": c.document_type,
                                                   "member_id": c.member_id} for c in new], **result}
        self.used.append({"tool": name, "args": arguments, "result": result})
        return result

    def _chip(self, document_type: str | None, member_id: str | None, document_id: str | None = None) -> str:
        assert self.ctx is not None
        chip = chip_for(self.ctx, document_type, member_id, document_id, self.language)
        self.chips[chip.id] = chip
        return chip.id

    # ---------- schemes (always) ----------

    def _list_schemes(self) -> dict[str, Any]:
        out = []
        for s in load_schemes():
            card = scheme_card(s, self.language)
            out.append({"scheme_id": s.id, "name": card.name, "short_name": card.short,
                        "benefit": {"text": card.benefit.text, "verified": card.benefit.status == "verified"}})
        return {"schemes": out, "note": "Kaagaz knows only these 5 Maharashtra schemes."}

    def _get_scheme_rules(self, scheme: str) -> dict[str, Any]:
        s = find_scheme(scheme)
        if s is None:
            return {"error": f"{scheme!r} is not one of the 5 schemes Kaagaz knows",
                    "known": [x.id for x in load_schemes()]}
        card = scheme_card(s, self.language)
        raw = {r.id: r for r in s.rules}
        rules = []
        for line in card.rules:
            r = raw[line.rule_id]
            rules.append({"rule_id": line.rule_id, "rule": line.text, "value": r.value, "status": line.status,
                          "verified": line.status == "verified", "interpretation": r.interpretation,
                          "source_urls": [x.url for x in line.sources if x.url]})
        return {
            "scheme_id": s.id, "name": card.name, "short_name": card.short,
            "benefit": {"text": card.benefit.text, "status": card.benefit.status,
                        "verified": card.benefit.status == "verified",
                        "source_urls": [x.url for x in card.benefit.sources if x.url]},
            "rules": rules,
            "other_proof_needed": [{"text": p.text, "status": p.status, "verified": p.status == "verified"}
                                   for p in card.other_proof],
            # TODO(developer): where to apply is not in data/schemes yet; until it is, the answer is "ask at the office".
            "where_to_apply": None,
            "note": "No where_to_apply: Kaagaz has no verified information on where to apply; say to ask at the "
                    "office. Unverified rules: say to check at the office.",
        }

    # ---------- the family (only with a check) ----------

    def _member_id(self, member: str) -> str | None:
        assert self.ctx is not None
        key = comparison_key(member)
        for m in self.ctx.data.members:
            names = [comparison_key(n) for n in (m.name_en, m.name_mr) if n]
            firsts = [comparison_key(n.split()[0]) for n in (m.name_en, m.name_mr) if n and n.split()]
            if key in (comparison_key(m.member_id), *names, *firsts):
                return m.member_id
        return None

    def _get_family(self) -> dict[str, Any]:
        assert self.ctx is not None
        members = []
        for m in self.ctx.data.members:
            members.append({"member_id": m.member_id, "name_from_document": _clip(m.name_en),
                            "name_devanagari_from_document": _clip(m.name_mr),
                            "relation_from_document": _clip(m.relation_en), "age": m.age,
                            "on_ration_card": m.on_ration_card,
                            "documents_linked": self.ctx.member_documents.get(m.member_id)})
        return {"members": members, "document_types_found": self.ctx.data.documents,
                "check": "a live check" if self.ctx.source == "session" else "a saved check"}

    def _get_member_results(self, member: str) -> dict[str, Any]:
        assert self.ctx is not None
        member_id = self._member_id(member)
        if member_id is None:
            return {"error": f"no member {member!r}; use a member_id from get_family"}
        results = [{"scheme_id": o.scheme_id, "scheme": scheme_short(o.scheme_id, self.language), "outcome": o.outcome,
                    "meaning": OUTCOME_MEANING.get(o.outcome, o.outcome), "reasons_shown_to_family": o.reasons,
                    "warnings_shown_to_family": o.warnings}
                   for o in self.ctx.data.outcomes if o.member_id == member_id]
        return {"member_id": member_id, "name_from_document": member_name(self.ctx, member_id, "en"),
                "results": results, "note": "Never say more than 'eligible on these documents': the office decides."}

    def _problem(self, p: Any) -> dict[str, Any]:
        assert self.ctx is not None
        out = {"type": p.type, "meaning": PROBLEM_MEANING.get(p.type, p.type), "member_id": p.member_id,
               "member_name_from_document": member_name(self.ctx, p.member_id, "en"),
               "document_types": p.document_types, "waits_for_clearer_photo": p.waiting}
        if p.type in ("missing_document", "unreadable") or p.waiting:
            out["chips"] = self._problem_chips(p)
        return out

    def _problem_chips(self, p: Any) -> list[str]:
        assert self.ctx is not None
        if p.type == "unreadable" or p.waiting:
            live = [u for u in self.ctx.unclear if u.document_id and u.member_id == p.member_id
                    and (u.document_type in p.document_types or not p.document_types)]
            if live:
                return [self._chip(u.document_type, u.member_id, u.document_id) for u in live]
        return [self._chip(t, p.member_id) for t in p.document_types or [None]]

    def _get_problems(self) -> dict[str, Any]:
        assert self.ctx is not None
        return {"problems": [self._problem(p) for p in self.ctx.data.problems],
                "not_identified": self._unidentified()}

    def _unidentified(self) -> dict[str, Any] | None:
        assert self.ctx is not None
        items = [u for u in self.ctx.unclear if u.document_id and u.document_type is None and u.member_id is None]
        if not items:
            return None
        return {"count": len(items), "meaning": "papers that looked like documents but could not be identified",
                "chips": [self._chip(None, None, u.document_id) for u in items]}

    def _get_missing_documents(self) -> dict[str, Any]:
        assert self.ctx is not None
        missing, unclear, renew = [], [], []
        for p in self.ctx.data.problems:
            who = {"member_id": p.member_id, "member_name_from_document": member_name(self.ctx, p.member_id, "en")}
            for t in p.document_types or [None]:
                item = {**who, "document_type": t, "document": document_name(t, self.language)}
                if p.type == "missing_document":
                    missing.append({**item, "chips": [self._chip(t, p.member_id)]})
                elif p.type == "unreadable" or p.waiting:
                    unclear.append({**item, "chips": self._problem_chips(p)})
                elif p.type == "expired":
                    renew.append(item)
        return {"missing": missing, "need_clearer_photo": unclear, "may_need_renewal": renew,
                "not_identified": self._unidentified(),
                "note": "Only what this check found. Scheme documents rules are in get_scheme_rules."}

    def _get_plan(self) -> dict[str, Any]:
        assert self.ctx is not None
        steps = [{"number": n, "kind": s.kind, "visit": s.visit, "member_id": s.member_id,
                  "member_name_from_document": member_name(self.ctx, s.member_id, "en"),
                  "text_shown_to_family": s.voice, "office": _fact(s.office), "bring": [_fact(b) for b in s.bring],
                  "fee": _fact(s.fee), "time_limit": _fact(s.time_limit)}
                 for n, s in enumerate(self.ctx.data.steps, 1)]
        return {"steps": steps, "language_of_texts": self.ctx.language,
                "note": "Facts with verified false: say to confirm at the office."}

    def _get_office_facts(self, document_type: str | None = None) -> dict[str, Any]:
        t = load_voice(self.language)
        shown = lambda f: None if f is None else {"value": f.value, "shown_as": t.values.get(f.value, f.value),  # noqa: E731
                                                 "verified": f.status == "verified", "source_url": f.source_url}
        out = []
        for p in load_fixes().values():
            if document_type and p.corrects != document_type and not any(f.wrong_document == document_type for f in p.fixes):
                continue
            out.append({"procedure_id": p.id, "title": p.title, "for": [f"{f.issue}: {f.wrong_document}" for f in p.fixes],
                        "office": shown(p.office), "how": p.steps, "bring": [shown(f) for f in p.bring],
                        "fee": shown(p.fee), "time_limit": shown(p.time_limit), "cautions": [shown(f) for f in p.cautions],
                        "optional": p.optional, "verified": p.status == "verified", "source_url": p.source_url})
        return {"procedures": out, "note": "Office types only, no addresses. fee null: Kaagaz has no fee information "
                                           "(never say it is free). Unverified facts: say to confirm at the office."}


# ---------- tool schemas (OpenAI function-calling format) ----------

def _fn(name: str, description: str, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}}


SCHEME_TOOLS = [
    _fn("list_schemes", "The 5 schemes Kaagaz knows: ids, names and one-line benefits."),
    _fn("get_scheme_rules", "One scheme's eligibility rules and documents, each with its status, source URLs and whether "
        "it is verified.", {"scheme": {"type": "string", "description": "scheme id or name"}}, ["scheme"]),
]
FAMILY_TOOLS = [
    _fn("get_family", "The family on this check: members (names read from documents), ages, relations, documents."),
    _fn("get_member_results", "One member's result for each scheme, as decided by the rules engine, with the reasons "
        "shown to the family.", {"member": {"type": "string", "description": "member_id or name"}}, ["member"]),
    _fn("get_problems", "Every problem this check found (mismatches, missing, unreadable or old documents)."),
    _fn("get_missing_documents", "Documents this check did not find, documents that need a clearer photo, and an income "
        "certificate that may need renewal."),
    _fn("get_plan", "The fix plan shown to the family: steps, offices, documents to bring, fees, time limits."),
    _fn("get_office_facts", "Verified offices and procedures for getting or correcting a document: office, how, what to "
        "bring, fee, time limit, cautions.",
        {"document_type": {"type": ["string", "null"], "description": "identity_card, ration_card, "
                                                                      "income_certificate, caste_certificate or null"}}),
]
REPLY_TOOL = _fn(
    "reply", "Give the final answer (call exactly once, after looking things up).",
    {"kind": {"type": "string", "enum": ["answer", "out_of_scope", "id_number", "other_language"],
              "description": "out_of_scope / id_number / other_language: the app shows a fixed reply; text is ignored"},
     "text": {"type": "string", "description": "the answer, in the requested language, under 80 words"},
     "chips": {"type": "array", "items": {"type": "string"},
               "description": "chip ids from tool results that help (e.g. a photo of a missing document); may be empty"}},
    ["kind", "text", "chips"])


# ---------- suggested questions (after a check) ----------

def suggestions(ctx: FamilyContext, language: str, limit: int = 3) -> list[str]:
    """Up to `limit` questions from templates, about this family's own problems, missing and unclear documents first.
    No model is involved."""
    t = load_ask(language).suggestions
    out: list[str] = []

    def add(text: str) -> None:
        if text not in out:
            out.append(text)

    def name(member_id: str | None) -> str:
        return member_name(ctx, member_id, language) or load_voice(language).household

    order = ("missing_document", "unreadable", "expired", "name_mismatch", "dob_mismatch", "not_on_ration_card")
    seen_types: set[str] = set()
    for kind in order:  # one question per problem type first, then the rest
        for p in ctx.data.problems:
            if p.type != kind or kind in seen_types:
                continue
            doc = document_name(p.document_types[0] if p.document_types else None, language)
            if kind == "missing_document":
                add(t["missing_document"].format(member=name(p.member_id), document=doc))
            elif kind == "unreadable":
                add(t["unclear"].format(member=name(p.member_id), document=doc) if p.member_id else t["unclear_unknown"])
            else:
                add(t[kind].format(member=name(p.member_id)))
            seen_types.add(kind)
    offices = [s.office.text for s in ctx.data.steps if s.kind == "fix" and s.office]
    if offices:
        add(t["office"].format(office=offices[0]))
    if ctx.data.problems:
        add(t["which_missing"])
    adults = [m for m in ctx.data.members if (m.age or 0) >= 18]
    if adults:
        add(t["schemes"].format(member=name(adults[0].member_id)))
    return out[:limit]
