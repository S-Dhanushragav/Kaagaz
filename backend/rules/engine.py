"""Rules engine: deterministic eligibility for each member and scheme. No LLM calls.

Outcome for a member and a scheme, in this order:
1. not_eligible           a rule fails on a value no issue casts doubt on (e.g. a man for Ladki Bahin)
2. blocked_by_issues      a needed value is missing or doubtful, or the member has blocker issues: fix first
3. check_at_office        a rule with conflicting sources lands in its unclear band
4. eligible_on_documents  everything the documents can show passes
Every result lists the rules used (value, status, source, interpretation), the reasons, the
needs_other_proof items the documents cannot show, and warnings (e.g. income certificate renewal).
"""

import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from rules.loader import Rule, Scheme, SharedRules, load_schemes, load_shared
from schemas.documents import DocumentExtraction
from schemas.household import Household, HouseholdMember
from schemas.issues import Issue

Outcome = Literal["eligible_on_documents", "not_eligible", "check_at_office", "blocked_by_issues"]
RuleOutcome = Literal["pass", "fail", "needs_other_proof", "check_at_office", "blocked", "warning"]

INCOME_CHECKS = {"income_max", "income_bands", "income_certificate_unless_card"}


class RuleResult(BaseModel):
    rule_id: str
    check: str
    outcome: RuleOutcome
    reason: str
    value: Any  # the rule's value
    actual: Any = None  # the household value it was compared with
    status: str
    source: str
    source_url: str | None
    interpretation: str | None = None


class OtherProofItem(BaseModel):
    id: str
    text: str
    status: str
    source: str


class SchemeResult(BaseModel):
    scheme_id: str
    scheme_name: str
    member_id: str
    outcome: Outcome
    reasons: list[str]
    rules: list[RuleResult]
    needs_other_proof: list[OtherProofItem]
    blocking_issues: list[Issue]
    warnings: list[str]


# ---------- facts from the household ----------

def category_code(doc: DocumentExtraction) -> str | None:
    """Caste category code (SC, ST, NB, OBC, VJNT) from a caste certificate's printed category."""
    if doc.fields is None:
        return None
    en = getattr(doc.fields, "category_en", None) or ""
    mr = getattr(doc.fields, "category_mr", None) or ""
    if re.search(r"\(SC\)|Scheduled Caste", en) or "अनुसूचित जाती" in mr:
        return "SC"
    if re.search(r"\(ST\)|Scheduled Tribe", en) or "अनुसूचित जमाती" in mr:
        return "ST"
    if "Neo-Buddhist" in en or "नवबौद्ध" in mr:
        return "NB"
    if re.search(r"\(OBC\)|Other Backward", en):
        return "OBC"
    if "VJNT" in en or "Vimukta" in en:
        return "VJNT"
    return None


def financial_year_start(reference: date) -> date:
    """1 April on or before the reference date."""
    return date(reference.year if reference.month >= 4 else reference.year - 1, 4, 1)


class _Facts:
    def __init__(self, hh: Household, member: HouseholdMember) -> None:
        self.hh, self.member = hh, member
        self.blockers = [i for i in hh.issues if i.severity == "blocker"]
        self.member_blockers = [i for i in self.blockers if i.member_id == member.member_id]

    def doc_blockers(self, doc_ids: list[str]) -> list[Issue]:
        return [i for i in self.blockers if set(i.documents) & set(doc_ids)]

    def missing(self, doc_type: str) -> list[Issue]:
        return [i for i in self.blockers if i.type == "missing_document" and i.evidence.get("document_type") == doc_type]

    @property
    def age_doubtful(self) -> bool:
        return any(i.type == "dob_mismatch" for i in self.member_blockers)

    @property
    def income_doc(self) -> DocumentExtraction | None:
        doc_id = self.hh.income_document_id
        return self.hh.documents.get(doc_id) if doc_id else None

    @property
    def income(self) -> int | None:
        doc = self.income_doc
        return getattr(doc.fields, "annual_income", None) if doc and doc.fields else None

    @property
    def income_doubtful(self) -> bool:
        return bool(self.hh.income_document_id and self.doc_blockers([self.hh.income_document_id]))

    def caste_docs(self, member_id: str | None = None) -> list[tuple[str, DocumentExtraction]]:
        docs = [(i, d) for i, d in self.hh.documents.items() if d.doc_type == "caste_certificate"]
        if member_id is not None:
            mine = set(self.hh.member(member_id).documents.get("caste_certificate", []))
            docs = [(i, d) for i, d in docs if i in mine]
        return docs


# ---------- checks ----------

def _result(rule: Rule, outcome: RuleOutcome, reason: str, actual: Any = None) -> RuleResult:
    return RuleResult(rule_id=rule.id, check=rule.check, outcome=outcome, reason=reason, value=rule.value,
                      actual=actual, status=rule.status, source=rule.source, source_url=rule.source_url,
                      interpretation=rule.interpretation)


def _age(rule: Rule, f: _Facts, ok: bool, wording: str) -> RuleResult:
    m = f.member
    if m.age is None:
        return _result(rule, "blocked", "age unknown (date of birth not readable)")
    if f.age_doubtful:
        return _result(rule, "blocked", "dates of birth differ between documents", m.age)
    src = "identity card" if m.age_source == "identity_card" else "ration card"
    return _result(rule, "pass" if ok else "fail", f"age {m.age} ({src}) {'meets' if ok else 'does not meet'} {wording}", m.age)


def _check(rule: Rule, scheme: Scheme, f: _Facts) -> RuleResult:
    m, v = f.member, rule.value
    if rule.check == "gender":
        want = {"female": "F", "male": "M"}[v]
        if m.gender is None:
            return _result(rule, "blocked", "gender not readable")
        return _result(rule, "pass" if m.gender == want else "fail", f"gender {m.gender}, needs {v}", m.gender)
    if rule.check == "age_min":
        return _age(rule, f, m.age is not None and m.age >= v, f"minimum {v}")
    if rule.check == "age_max":
        return _age(rule, f, m.age is not None and m.age <= v, f"maximum {v}")
    if rule.check == "age_below":
        return _age(rule, f, m.age is not None and m.age < v, f"below {v}")

    if rule.check in INCOME_CHECKS:
        exempt_cards = next((r.value["not_required_for_cards"] for r in scheme.rules
                             if r.check == "income_certificate_unless_card"), [])
        if f.income_doc is None:
            if f.hh.card_colour in exempt_cards:
                return _result(rule, "pass", f"no income certificate; {f.hh.card_colour} ration card satisfies "
                                             "the income requirement (our reading)", f.hh.card_colour)
            return _result(rule, "blocked", "income certificate missing")
        if rule.check == "income_certificate_unless_card":
            return _result(rule, "pass", "income certificate present", f.hh.income_document_id)
        if f.income is None:
            return _result(rule, "blocked", "income not readable on the income certificate")
        if f.income_doubtful:
            return _result(rule, "blocked", "the income certificate has issues to fix first", f.income)
        if rule.check == "income_max":
            ok = f.income <= v
            return _result(rule, "pass" if ok else "fail", f"family income {f.income} {'<=' if ok else '>'} {v}", f.income)
        if f.income <= v["pass_max"]:  # income_bands (conflicting sources)
            return _result(rule, "pass", f"family income {f.income} <= {v['pass_max']}", f.income)
        if f.income > v["fail_above"]:
            return _result(rule, "fail", f"family income {f.income} > {v['fail_above']}", f.income)
        return _result(rule, "check_at_office",
                       f"family income {f.income} is between {v['pass_max']} and {v['fail_above']}; "
                       "sources disagree on the limit", f.income)

    if rule.check == "caste_household":
        qualifying = [(i, d) for i, d in f.caste_docs() if category_code(d) in v["qualifying"]]
        clean = [i for i, _ in qualifying if not f.doc_blockers([i])]
        if clean:
            return _result(rule, "pass", f"household has a {'/'.join(v['qualifying'])} caste certificate", clean)
        if qualifying:
            return _result(rule, "blocked", "the qualifying caste certificate has issues to fix first",
                           [i for i, _ in qualifying])
        return _result(rule, "needs_other_proof",
                       f"no {'/'.join(v['qualifying'])} caste certificate; other qualifying categories need other proof")

    if rule.check == "caste_applicant":
        own = f.caste_docs(m.member_id)
        if not own:
            others = [i for i, d in f.caste_docs() if category_code(d) in v["qualifying"]]
            if others:
                return _result(rule, "check_at_office", "only another household member has a qualifying caste "
                                                        "certificate (our reading)", others)
            return _result(rule, "blocked", "no caste certificate for the applicant")
        if all(f.doc_blockers([i]) for i, _ in own):
            return _result(rule, "blocked", "the applicant's caste certificate has issues to fix first", [i for i, _ in own])
        codes = {category_code(d) for i, d in own if not f.doc_blockers([i])}
        if codes & set(v["qualifying"]):
            return _result(rule, "pass", f"applicant's own caste certificate: {sorted(codes & set(v['qualifying']))}", sorted(codes))
        return _result(rule, "fail", f"applicant's caste category {sorted(c for c in codes if c)} is not "
                                     f"{'/'.join(v['qualifying'])}", sorted(c for c in codes if c))

    if rule.check == "documents":
        missing = []
        if v.get("ration_card") and not f.hh.ration_card_id:
            missing.append("ration card")
        if v.get("identity_card") == "every_adult_on_ration_card":
            for mem in f.hh.members:
                if not mem.on_ration_card:
                    continue
                if mem.age is None:
                    missing.append(f"age of {mem.member_id} unknown (adult identity card check)")
                elif mem.age >= 18 and not mem.documents.get("identity_card"):
                    missing.append(f"identity card of {mem.name_en or mem.member_id}")
        if v.get("caste_certificate") and not f.caste_docs():
            missing.append("caste certificate")
        if v.get("income_certificate") and f.income_doc is None:
            missing.append("income certificate")
        if missing:
            return _result(rule, "blocked", "missing: " + "; ".join(missing), missing)
        return _result(rule, "pass", "required documents present")

    raise ValueError(f"unknown check {rule.check!r} in {scheme.id}")


def _validity_warning(shared: SharedRules, f: _Facts) -> RuleResult | None:
    rule = shared.rule("income_certificate_validity")
    doc = f.income_doc
    issue_date = getattr(doc.fields, "issue_date", None) if doc and doc.fields else None
    if issue_date is None:
        return None
    issued = datetime.strptime(issue_date, "%d/%m/%Y").date()
    start = financial_year_start(f.hh.reference_date)
    if issued < start:
        return _result(rule, "warning", f"income certificate issued {issue_date}, before {start:%d/%m/%Y}: "
                                        f"{rule.value['message']}", issue_date)
    return None


# ---------- evaluation ----------

def evaluate_member(hh: Household, member: HouseholdMember, scheme: Scheme, shared: SharedRules) -> SchemeResult:
    f = _Facts(hh, member)
    results = [_check(rule, scheme, f) for rule in scheme.rules]
    warnings = []
    if any(r.check in INCOME_CHECKS for r in scheme.rules):
        w = _validity_warning(shared, f)
        if w:
            results.append(w)
            warnings.append(w.reason)

    fails = [r for r in results if r.outcome == "fail"]
    blocked = [r for r in results if r.outcome == "blocked"]
    office = [r for r in results if r.outcome == "check_at_office"]

    blocking: list[Issue] = list(f.member_blockers)
    if any(r.check in INCOME_CHECKS for r in blocked):
        blocking += f.missing("income_certificate")
        if hh.income_document_id:
            blocking += f.doc_blockers([hh.income_document_id])
    for r in blocked:
        if r.check in ("caste_household", "caste_applicant") and isinstance(r.actual, list):
            blocking += f.doc_blockers(r.actual)
        if r.check == "documents":
            blocking += f.missing("identity_card")
    blocking = list({id(i): i for i in blocking}.values())

    if fails:
        outcome: Outcome = "not_eligible"
        reasons = [r.reason for r in fails]
    elif blocked or f.member_blockers:
        outcome = "blocked_by_issues"
        reasons = [r.reason for r in blocked] + [i.message for i in f.member_blockers]
    elif office:
        outcome = "check_at_office"
        reasons = [r.reason for r in office]
    else:
        outcome = "eligible_on_documents"
        reasons = [r.reason for r in results if r.outcome == "pass"]

    other = [OtherProofItem(id=p.id, text=p.text, status=p.status, source=p.source) for p in scheme.needs_other_proof]
    other += [OtherProofItem(id=r.rule_id, text=r.reason, status=r.status, source=r.source)
              for r in results if r.outcome == "needs_other_proof"]
    return SchemeResult(
        scheme_id=scheme.id, scheme_name=scheme.name.get("en", scheme.id), member_id=member.member_id,
        outcome=outcome, reasons=reasons, rules=results, needs_other_proof=other,
        blocking_issues=blocking if outcome == "blocked_by_issues" else [], warnings=warnings,
    )


def evaluate(hh: Household, schemes: tuple[Scheme, ...] | None = None,
             shared: SharedRules | None = None) -> list[SchemeResult]:
    """Every member x every scheme."""
    schemes = schemes if schemes is not None else load_schemes()
    shared = shared if shared is not None else load_shared()
    return [evaluate_member(hh, m, s, shared) for m in hh.members for s in schemes]
