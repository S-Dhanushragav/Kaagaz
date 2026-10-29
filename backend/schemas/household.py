"""The household built from a family's documents (input to the rules engine)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from clients.llm import TokenUsage
from schemas.documents import DocumentExtraction
from schemas.issues import Issue


class HouseholdMember(BaseModel):
    member_id: str  # "r1", "r2", ... in ration-card order; "x1", ... for people not on the ration card
    on_ration_card: bool
    name_mr: str | None = None
    name_en: str | None = None
    relation_en: str | None = None
    gender: Literal["M", "F"] | None = None
    dob: date | None = None
    age: int | None = None
    age_source: Literal["identity_card", "ration_card"] | None = None
    documents: dict[str, list[str]] = {}  # doc type -> document ids linked to this member


class LinkDecision(BaseModel):
    """How one document was linked to a member (or not)."""

    document_id: str
    member_id: str | None
    score: float  # best name score, 0-100
    method: Literal["fuzzy", "tiebreak", "llm", "none"]
    reason: str


class Household(BaseModel):
    reference_date: date
    ration_card_id: str | None
    card_colour: Literal["yellow", "orange", "white"] | None
    members: list[HouseholdMember]
    documents: dict[str, DocumentExtraction]  # by id, after duplicates are merged
    income_document_id: str | None  # the household's income certificate used for income rules
    issues: list[Issue]
    links: list[LinkDecision] = []
    llm_calls: int = 0  # name-adjudicator calls (text model)
    verification_calls: int = 0  # name re-reads (vision model) before a name mismatch is reported
    usage: TokenUsage = TokenUsage()  # tokens of both, summed

    def member(self, member_id: str) -> HouseholdMember:
        return next(m for m in self.members if m.member_id == member_id)
