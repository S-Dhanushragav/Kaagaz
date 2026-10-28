"""Extracted-document schemas. Field names match synthetic ground_truth.json.

Every field is required but nullable: null means "not readable on the document". The reader
never fills a value it could not read, and `unreadable_fields` is derived from those nulls.
"""

import re
from datetime import datetime
from typing import Annotated, Any, Iterator, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from vision.text import MASKED_ID, mask_identity_number

DocType = Literal["ration_card", "identity_card", "income_certificate", "caste_certificate", "other"]

_FY = re.compile(r"^\d{4}-\d{2}$")


def _check_date(v: str | None) -> str | None:
    if v is None:
        return None
    try:
        datetime.strptime(v, "%d/%m/%Y")
    except ValueError:
        raise ValueError("must be a real date written DD/MM/YYYY") from None
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", v):
        raise ValueError("must be a real date written DD/MM/YYYY")
    return v


def _check_fy(v: str | None) -> str | None:
    if v is not None and not _FY.fullmatch(v):
        raise ValueError("must look like YYYY-YY, e.g. 2025-26")
    return v


def _parse_rupees(v: Any) -> Any:
    """'Rs. 1,20,000' -> 120000. Only digits are kept; anything without digits stays as-is."""
    if isinstance(v, str):
        digits = "".join(ch for ch in v if ch.isdigit())
        return int(digits) if digits else v
    return v


def _mask_id(v: Any) -> Any:
    """Accept masked ('XXXX XXXX 1234'), last 4 digits, or a full number; always store masked."""
    if v is None:
        return None
    if isinstance(v, str) and MASKED_ID.fullmatch(v.strip()):
        return v.strip()
    return mask_identity_number(str(v))


Text = str | None
DateStr = Annotated[str | None, AfterValidator(_check_date), Field(description="DD/MM/YYYY")]
Age = Annotated[int | None, Field(ge=0, le=120)]
Rupees = Annotated[int | None, BeforeValidator(_parse_rupees), Field(ge=0, description="rupees, digits only")]
FinancialYear = Annotated[str | None, AfterValidator(_check_fy), Field(description="YYYY-YY")]
MaskedId = Annotated[
    str | None, BeforeValidator(_mask_id), Field(description="only the last 4 digits, as 'XXXX XXXX 1234'")
]


class _Fields(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RationCardMember(_Fields):
    name_mr: Text
    name_en: Text
    relation_mr: Text
    relation_en: Text
    gender_mr: Text
    gender_en: Text
    age: Age


class RationCardFields(_Fields):
    card_number: Text
    category_mr: Text
    category_en: Text
    head_name_mr: Text
    head_name_en: Text
    address_mr: Text
    address_en: Text
    members: list[RationCardMember]


class IdentityCardFields(_Fields):
    name_mr: Text
    name_en: Text
    dob: DateStr
    gender_mr: Text
    gender_en: Text
    id_number: MaskedId


class IncomeCertificateFields(_Fields):
    certificate_number: Text
    name_mr: Text
    name_en: Text
    address_mr: Text
    address_en: Text
    annual_income: Rupees
    financial_year: FinancialYear
    issue_date: DateStr
    office_mr: Text
    office_en: Text


class CasteCertificateFields(_Fields):
    certificate_number: Text
    name_mr: Text
    name_en: Text
    dob: DateStr
    category_mr: Text
    category_en: Text
    address_mr: Text
    address_en: Text
    issue_date: DateStr
    office_mr: Text
    office_en: Text


AnyFields = RationCardFields | IdentityCardFields | IncomeCertificateFields | CasteCertificateFields

FIELD_MODELS: dict[str, type[_Fields]] = {
    "ration_card": RationCardFields,
    "identity_card": IdentityCardFields,
    "income_certificate": IncomeCertificateFields,
    "caste_certificate": CasteCertificateFields,
}


# Fields that drive decisions (matching, eligibility). When a document has several frames, each
# frame is read separately and these are accepted only if at least 2 frames agree; otherwise null.
# Other fields (addresses, offices, numbers, relation, age) are display-only: read from the best frame.
# Paths use "members." for every ration-card member row. The ration card's category is its card type
# (AAY / PHH / NPHH), i.e. the card "colour".
DECISION_FIELDS: dict[str, frozenset[str]] = {
    "ration_card": frozenset({
        "head_name_mr", "head_name_en", "category_mr", "category_en",
        "members.name_mr", "members.name_en", "members.gender_mr", "members.gender_en",
    }),
    "identity_card": frozenset({"name_mr", "name_en", "dob", "gender_mr", "gender_en", "id_number"}),
    "income_certificate": frozenset({"name_mr", "name_en", "annual_income", "issue_date"}),
    "caste_certificate": frozenset({"name_mr", "name_en", "dob", "category_mr", "category_en", "issue_date"}),
}

# Fields without which a document is not usable. Each group is satisfied if any of its fields is
# non-null (e.g. the name in Marathi or English). If a group stays null, ask for a close-up.
KEY_FIELDS: dict[str, list[tuple[str, ...]]] = {
    "ration_card": [("head_name_mr", "head_name_en"), ("members.name_mr", "members.name_en")],
    "identity_card": [("name_mr", "name_en"), ("dob",), ("id_number",)],
    "income_certificate": [("name_mr", "name_en"), ("annual_income",), ("issue_date",)],
    "caste_certificate": [("name_mr", "name_en"), ("category_mr", "category_en"), ("issue_date",)],
}


def field_pattern(path: str) -> str:
    """'members[2].name_mr' -> 'members.name_mr' (the form used in DECISION_FIELDS / KEY_FIELDS)."""
    return re.sub(r"\[\d+\]", "", path)


def null_paths(value: Any, prefix: str = "") -> Iterator[str]:
    """Paths of null values, e.g. 'members[2].age'."""
    if isinstance(value, BaseModel):
        value = value.model_dump()
    if isinstance(value, dict):
        for k, v in value.items():
            yield from null_paths(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from null_paths(v, f"{prefix}[{i}]")
    elif value is None:
        yield prefix


class DocumentExtraction(BaseModel):
    """Reader output for one document. `fields` is None for 'other' or unreadable documents."""

    document_id: str
    doc_type: DocType | None = None  # None only when the document could not be read at all
    fields: AnyFields | None = None
    unreadable_fields: list[str] = []
    unreadable: bool = False
    error: str | None = None
    disagreed_fields: list[str] = []  # decision fields nulled because frames did not agree
    # Time between the frames whose reads agreed on the document type. Frames close together share
    # more of the same blur, so their agreement is weaker evidence.
    agreement_gap_s: float | None = None
    agreement_strength: Literal["strong", "weak"] | None = None  # strong: >= 0.5 s apart
    needs_retake: bool = False  # key fields still null: the app should ask for a close-up of this document
    retake_reasons: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _fields_by_type(cls, data: Any) -> Any:
        # Pick the field model from doc_type instead of letting the union guess.
        if isinstance(data, dict) and isinstance(data.get("fields"), dict) and data.get("doc_type") in FIELD_MODELS:
            data = {**data, "fields": FIELD_MODELS[data["doc_type"]].model_validate(data["fields"])}
        return data


# ---------- structured-output schema sent to the model ----------

def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline_refs(defs[node["$ref"].split("/")[-1]], defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def _schema_for(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    return _inline_refs(schema, schema.get("$defs", {}))


def _reply_branch(doc_type: str, fields_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "doc_type": {"type": "string", "enum": [doc_type]},
            "fields": fields_schema,
        },
        "required": ["doc_type", "fields"],
        "additionalProperties": False,
    }


def reply_json_schema() -> dict[str, Any]:
    """JSON schema for the model's reply: {"document": one of {doc_type, fields}}.

    Each choice pairs one doc_type with its own field model ('other' with fields null), so a type
    can't carry another type's fields. The choice is wrapped in a "document" key because the Meta
    API requires a plain object at the top level (no anyOf there). Refs inlined, no extra keys.
    """
    return {
        "type": "object",
        "properties": {
            "document": {
                "anyOf": [
                    *(_reply_branch(t, _schema_for(m)) for t, m in FIELD_MODELS.items()),
                    _reply_branch("other", {"type": "null"}),
                ]
            }
        },
        "required": ["document"],
        "additionalProperties": False,
    }
