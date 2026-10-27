"""Ground-truth models for synthetic households (written to ground_truth.json)."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

DocType = Literal["ration_card", "identity_card", "income_certificate", "caste_certificate"]
ErrorType = Literal[
    "name_mismatch", "dob_mismatch", "expired", "missing_document", "not_on_ration_card"
]


class Name(BaseModel):
    mr: str
    en: str


class Member(BaseModel):
    id: str
    given: Name
    middle: Name  # father's or husband's given name
    surname: Name
    relation: Name
    gender: Literal["M", "F"]
    dob: date
    age: int
    on_ration_card: bool = True

    @property
    def full_name(self) -> Name:
        return Name(
            mr=f"{self.given.mr} {self.middle.mr} {self.surname.mr}",
            en=f"{self.given.en} {self.middle.en} {self.surname.en}",
        )


class Document(BaseModel):
    id: str
    type: DocType
    member_ids: list[str]
    fields: dict[str, Any]  # exactly as printed on the document (errors included)
    files: dict[str, str] = {}
    photo: dict[str, Any] = {}  # photo-like augmentation parameters


class PlantedError(BaseModel):
    type: ErrorType
    member_id: str
    documents: list[str]
    field: str | None = None
    expected: Any = None
    printed: Any = None
    note: str | None = None


class Household(BaseModel):
    id: str
    seed: int
    reference_date: date
    members: list[Member]
    documents: list[Document]
    planted_errors: list[PlantedError]
