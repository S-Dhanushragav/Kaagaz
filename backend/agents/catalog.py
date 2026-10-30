"""The scheme catalog for the app (GET /schemes): each scheme's rules as short lines in the family's language.

Values, statuses and sources come only from data/schemes/*.yaml (rules/loader.py); the wording comes from the
`catalog` section of data/templates/reasons/{en,hi,mr}.yaml. Nothing here decides eligibility.
"""

from typing import Any

from pydantic import BaseModel

from agents.reasons import ReasonTemplates, inr, load_reasons
from rules.loader import Rule, Scheme, load_schemes

GENDER = {"female": "F", "male": "M"}


class Source(BaseModel):
    source: str
    url: str | None


class CatalogLine(BaseModel):
    rule_id: str
    check: str
    text: str
    status: str  # 'verified' | 'conflict' | 'unverified'
    sources: list[Source]  # for a conflict: every reported value's source
    last_checked: str


class CatalogBenefit(BaseModel):
    text: str
    status: str
    sources: list[Source]
    last_checked: str


class CatalogScheme(BaseModel):
    id: str
    name: str  # full name
    short: str  # short name (the household matrix)
    benefit: CatalogBenefit
    rules: list[CatalogLine]
    other_proof: list[CatalogLine]  # needs other proof (text as written in the YAML, English)


def _or(items: list[str], t: ReasonTemplates) -> str:
    return f" {t.catalog['or']} ".join(items)


def _documents(value: dict[str, Any], t: ReasonTemplates) -> str:
    items = []
    for kind, need in value.items():
        if kind == "identity_card" and need == "every_adult_on_ration_card":
            items.append(t.catalog["every_adult_identity_card"])
        elif need:
            items.append(t.missing.get(kind, kind))
    return ", ".join(items)


def rule_line(rule: Rule, t: ReasonTemplates) -> str | None:
    """One line for a rule, or None for a rule the family does not need to see (it only refines another)."""
    c, v = t.catalog, rule.value
    if rule.check == "gender":
        return c[f"gender.{GENDER[v]}"]
    if rule.check in ("age_min", "age_max", "age_below"):
        return c[rule.check].format(limit=v)
    if rule.check == "income_max":
        return c["income_max"].format(limit=inr(v))
    if rule.check == "income_bands":
        return c["income_bands"].format(low=inr(v["pass_max"]), high=inr(v["fail_above"]))
    if rule.check in ("caste_household", "caste_applicant"):
        return c[rule.check].format(categories=_or(v["qualifying"], t))
    if rule.check == "documents":
        return c["documents"].format(items=_documents(v, t))
    if rule.check == "income_certificate_unless_card":
        return c["income_certificate_unless_card"].format(
            cards=_or([t.words.get(card, card) for card in v["not_required_for_cards"]], t))
    return None


def _sources(rule: Any) -> list[Source]:
    reported = getattr(rule, "reported", [])
    pairs = [(r.source, r.source_url) for r in reported] or [(rule.source, rule.source_url)]
    return [Source(source=s, url=u) for s, u in dict.fromkeys(pairs)]


def scheme_card(scheme: Scheme, language: str) -> CatalogScheme:
    t = load_reasons(language)
    lines = []
    for rule in scheme.rules:
        text = rule_line(rule, t)
        if text is not None:
            lines.append(CatalogLine(rule_id=rule.id, check=rule.check, text=text, status=rule.status,
                                     sources=_sources(rule), last_checked=rule.last_checked.isoformat()))
    other = [CatalogLine(rule_id=p.id, check="other_proof", text=p.text, status=p.status, sources=_sources(p),
                         last_checked=p.last_checked.isoformat()) for p in scheme.needs_other_proof]

    def pick(names: dict[str, str]) -> str:
        return names.get(language) or names.get("en") or scheme.id

    b = scheme.benefit
    benefit = CatalogBenefit(text=pick(b.text), status=b.status, sources=_sources(b), last_checked=b.last_checked.isoformat())
    return CatalogScheme(id=scheme.id, name=pick(scheme.name), short=pick(scheme.short), benefit=benefit, rules=lines,
                         other_proof=other)


def catalog(language: str) -> list[CatalogScheme]:
    return [scheme_card(s, language) for s in load_schemes()]
