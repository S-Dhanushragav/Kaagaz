"""What a case file holds. Only these fields are ever stored (allow-list): no images, crops, videos, raw phone
numbers or ID numbers. `app/casefile.py` builds a CheckData from a finished session."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class User(_Strict):
    id: str
    phone_hash: str
    phone_last4: str
    language: str
    created: date


class StoredMember(_Strict):
    member_id: str
    name_mr: str | None
    name_en: str | None
    relation_en: str | None
    age: int | None
    on_ration_card: bool


class StoredProblem(_Strict):
    type: str
    member_id: str | None
    member_name: str | None  # English, for matching across checks
    member_name_mr: str | None
    document_types: list[str]
    waiting: bool  # waiting for a clearer photo


class StoredOutcome(_Strict):
    member_id: str
    scheme_id: str
    outcome: str
    reasons: list[str]  # in the check's language
    warnings: list[str]


class StoredFact(_Strict):
    text: str
    verified: bool  # False: shown with "confirm at the office"


class StoredStep(_Strict):
    index: int  # position in the plan (step_progress uses it)
    kind: str  # 'fix' | 'ask_at_office'
    visit: int | None
    office: StoredFact | None
    voice: str  # what the app showed
    speech: str  # what was spoken (TTS input), so a past check can still be listened to
    bring: list[StoredFact]
    fee: StoredFact | None
    time_limit: StoredFact | None
    member_id: str | None


class StoredAnswer(_Strict):
    question: str
    answer: str


class CheckData(_Strict):
    members: list[StoredMember]
    documents: list[str]  # document types found
    problems: list[StoredProblem]
    outcomes: list[StoredOutcome]
    steps: list[StoredStep]
    answers: list[StoredAnswer]


class CheckRecord(_Strict):
    id: str
    user_id: str
    session_id: str
    previous_id: str | None
    language: str
    created: datetime
    updated: datetime
    data: CheckData
    steps_done: dict[int, bool] = {}  # step index -> done


class FeedbackEntry(_Strict):
    session_id: str
    target: str
    value: Literal["up", "down"]
    comment: str | None
