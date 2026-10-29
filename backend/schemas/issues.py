"""Issues found by the household builder (deterministic code, no LLM)."""

from typing import Any, Literal

from pydantic import BaseModel

IssueType = Literal[
    "name_mismatch",  # the same person's name is spelled differently on two documents
    "dob_mismatch",  # the same person's date of birth differs between documents
    "not_on_ration_card",  # a document belongs to someone who is not on the ration card
    "missing_document",  # an expected document is not there
    "expired",  # income certificate may need renewal (warning only)
    "unreadable",  # a needed field could not be read: recapture that document
    "duplicate_merged",  # the same document was captured twice and merged (info)
    "name_verified",  # a spelling difference was not confirmed by a closer re-read (info)
]
Severity = Literal["blocker", "warning", "info"]


class Issue(BaseModel):
    type: IssueType
    severity: Severity
    member_id: str | None  # household member it concerns (None: household-level)
    documents: list[str]  # document ids involved
    evidence: dict[str, Any]  # exact values and which documents they came from
    message: str
