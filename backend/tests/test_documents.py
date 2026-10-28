import json

import pytest
from pydantic import ValidationError

from schemas.documents import (
    FIELD_MODELS,
    CasteCertificateFields,
    DocumentExtraction,
    IdentityCardFields,
    IncomeCertificateFields,
    RationCardFields,
    null_paths,
    reply_json_schema,
)
from synthetic.generate import build_household

IDENTITY = {
    "name_mr": "सुनील रमेश पाटील", "name_en": "Sunil Ramesh Patil", "dob": "05/03/1990",
    "gender_mr": "पुरुष", "gender_en": "Male", "id_number": "XXXX XXXX 8901",
}
INCOME = {
    "certificate_number": "SPEC/INC/1", "name_mr": "अ", "name_en": "A", "address_mr": "प", "address_en": "P",
    "annual_income": 120000, "financial_year": "2025-26", "issue_date": "01/10/2026",
    "office_mr": "क", "office_en": "O",
}


def test_ground_truth_fields_validate_against_schemas() -> None:
    """Field names match ground_truth.json: every synthetic document validates."""
    for i in range(1, 30):
        for doc in build_household(42, i).documents:
            FIELD_MODELS[doc.type].model_validate(doc.fields)


def test_full_identity_number_is_masked() -> None:
    for raw in ("012345678901", "0123 4567 8901", "8901", "XXXX XXXX 8901"):
        assert IdentityCardFields(**{**IDENTITY, "id_number": raw}).id_number == "XXXX XXXX 8901"
    with pytest.raises(ValidationError):
        IdentityCardFields(**{**IDENTITY, "id_number": "not readable"})


@pytest.mark.parametrize("bad", ["1990-03-05", "5/3/1990", "31/02/1990", "05.03.1990"])
def test_dates_must_be_real_dd_mm_yyyy(bad: str) -> None:
    with pytest.raises(ValidationError):
        IdentityCardFields(**{**IDENTITY, "dob": bad})


def test_rupees_and_financial_year() -> None:
    assert IncomeCertificateFields(**{**INCOME, "annual_income": "Rs. 1,20,000"}).annual_income == 120000
    with pytest.raises(ValidationError):
        IncomeCertificateFields(**{**INCOME, "annual_income": "one lakh"})
    with pytest.raises(ValidationError):
        IncomeCertificateFields(**{**INCOME, "financial_year": "2025/2026"})


def test_age_bounds() -> None:
    row = {"name_mr": "अ", "name_en": "A", "relation_mr": "र", "relation_en": "R",
           "gender_mr": "ग", "gender_en": "G", "age": 150}
    card = {"card_number": "1", "category_mr": None, "category_en": None, "head_name_mr": None,
            "head_name_en": None, "address_mr": None, "address_en": None, "members": [row]}
    with pytest.raises(ValidationError):
        RationCardFields(**card)


def test_nulls_allowed_but_fields_required_and_no_extras() -> None:
    nulls = {k: None for k in IDENTITY}
    assert IdentityCardFields(**nulls).id_number is None
    with pytest.raises(ValidationError):
        IdentityCardFields(**{k: v for k, v in IDENTITY.items() if k != "dob"})
    with pytest.raises(ValidationError):
        IdentityCardFields(**IDENTITY, confidence=0.9)


def test_null_paths() -> None:
    fields = IdentityCardFields(**{**IDENTITY, "dob": None, "gender_en": None})
    assert list(null_paths(fields)) == ["dob", "gender_en"]
    assert list(null_paths({"members": [{"age": 3}, {"age": None}]})) == ["members[1].age"]


def test_extraction_round_trip_picks_model_by_doc_type() -> None:
    ex = DocumentExtraction(document_id="d", doc_type="identity_card", fields=IdentityCardFields(**IDENTITY))
    back = DocumentExtraction.model_validate(json.loads(ex.model_dump_json()))
    assert isinstance(back.fields, IdentityCardFields)
    caste = DocumentExtraction.model_validate(
        {"document_id": "c", "doc_type": "caste_certificate",
         "fields": {k: None for k in CasteCertificateFields.model_fields}}
    )
    assert isinstance(caste.fields, CasteCertificateFields)


def test_reply_schema_is_strict_and_self_contained() -> None:
    schema = reply_json_schema()
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert "confidence" not in text

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for v in node.values():
                yield from objects(v)
        elif isinstance(node, list):
            for v in node:
                yield from objects(v)

    for obj in objects(schema):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_reply_schema_pairs_each_doc_type_with_its_own_fields() -> None:
    """A doc_type can only be combined with its own field model ('other' only with null)."""
    schema = reply_json_schema()
    assert schema["type"] == "object" and "anyOf" not in schema  # Meta: plain object at top level
    assert schema["required"] == ["document"]
    branches = schema["properties"]["document"]["anyOf"]
    pairs = {b["properties"]["doc_type"]["enum"][0]: b["properties"]["fields"] for b in branches}
    assert all(len(b["properties"]["doc_type"]["enum"]) == 1 for b in branches)
    assert set(pairs) == {*FIELD_MODELS, "other"}
    assert pairs["other"] == {"type": "null"}
    for doc_type, model in FIELD_MODELS.items():
        assert set(pairs[doc_type]["properties"]) == set(model.model_fields), doc_type
