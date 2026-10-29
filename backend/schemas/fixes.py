"""Fix knowledge base (data/fixes/*.yaml) and the fix plan the planner produces.

Every fact in a procedure (office, document to bring, fee, time limit, caution) carries its own
status and source, because a verified procedure can contain unverified facts.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from clients.llm import TokenUsage

Status = Literal["verified", "unverified"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(_Strict):
    value: str
    status: Status
    source_url: str | None
    note: str | None = None  # for the developer; never shown to the agent


class Fixes(_Strict):
    issue: str  # issue type, e.g. name_mismatch
    wrong_document: str  # document type that is corrected, or "any"


class FixProcedure(_Strict):
    id: str
    title: str
    fixes: list[Fixes]
    corrects: str | None
    office: Fact | None
    steps: list[str]
    bring: list[Fact]
    fee: Fact | None
    time_limit: Fact | None
    cautions: list[Fact]
    status: Status
    source_url: str | None
    last_checked: date
    optional: bool = False
    slowest: bool = False  # plan it first

    def facts(self) -> dict[str, Fact]:
        """Every fact, keyed by what it is ('office', 'fee', 'time_limit', 'bring', 'caution')."""
        out: dict[str, Fact] = {}
        for name in ("office", "fee", "time_limit"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        for i, f in enumerate(self.bring):
            out[f"bring[{i}]"] = f
        for i, f in enumerate(self.cautions):
            out[f"caution[{i}]"] = f
        return out


# ---------- the plan ----------

class PlannerIssue(BaseModel):
    """One issue as the planner sees it (from the household builder or the rules engine)."""

    id: str  # "i1", "i2", ...
    type: str
    severity: str
    member_id: str | None
    member_name: str | None
    member_name_mr: str | None = None  # Devanagari, for Hindi and Marathi sentences
    documents: dict[str, str]  # document id -> document type
    document_type: str | None = None  # missing / expired / to-be-corrected document type, when there is one
    values: dict[str, str] = {}  # document id -> the differing value (names or dates of birth)
    detail: str  # plain description


class FactUsed(BaseModel):
    fact: str  # office, fee, time_limit, bring[0], caution[0], ...
    value: str
    status: Status
    source_url: str | None


class FixStep(BaseModel):
    kind: Literal["question", "fix", "ask_at_office"]
    issue_ids: list[str]
    member_id: str | None = None
    procedure_id: str | None = None
    question: str | None = None
    question_kind: Literal["which_is_correct", "compare"] | None = None
    options: list[str] = []
    answer: str | None = None
    office: str | None = None
    bring: list[str] = []
    fee: str | None = None
    time_limit: str | None = None
    cautions: list[str] = []
    declaration: str | None = None
    facts: list[FactUsed] = []  # status and source of every fact in the step
    visit: int | None = None  # fix steps at the same office share one visit (1 = first)
    voice: str = ""  # filled by code from data/templates/voice (never written by the agent)


class FixPlan(BaseModel):
    steps: list[FixStep]
    source: Literal["agent", "agent_retry", "fallback"]
    language: str = "en"
    verification_errors: list[str] = []  # of the last rejected attempt
    attempts: int = 0
    turns: int = 0
    trace: list[dict] = []  # tool calls, tool results, reasoning
    usage: TokenUsage = TokenUsage()
