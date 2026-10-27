from collections import Counter
from datetime import datetime

import cv2
import numpy as np

from synthetic import names as N
from synthetic.generate import (
    EXPIRED_INCOME_CERT_AGE_DAYS,
    REFERENCE_DATE,
    VALID_INCOME_CERT_AGE_DAYS,
    age_on,
    build_household,
    fmt_date,
)
from synthetic.photo import photo_like
from synthetic.render import id_groups, rupees
from synthetic.scoring import matches, normalize, score

SEEDS = range(200)


def _households():
    return [build_household(42, i) for i in SEEDS]


def _doc(hh, doc_id):
    return next((d for d in hh.documents if d.id == doc_id), None)


def _days_old(date_str: str) -> int:
    return (REFERENCE_DATE - datetime.strptime(date_str, "%d/%m/%Y").date()).days


def test_same_seed_same_household() -> None:
    assert build_household(42, 3).model_dump_json() == build_household(42, 3).model_dump_json()
    assert build_household(42, 3).model_dump_json() != build_household(43, 3).model_dump_json()


def test_household_shape() -> None:
    for hh in _households():
        assert 2 <= len(hh.members) <= 6
        assert 0 <= len(hh.planted_errors) <= 3
        assert len({e.type for e in hh.planted_errors}) == len(hh.planted_errors)
        assert hh.members[0].relation.en == "Self"
        for m in hh.members:
            assert age_on(m.dob, REFERENCE_DATE) == m.age
        assert len({m.given.en for m in hh.members}) == len(hh.members)


def test_identity_numbers_can_never_be_real() -> None:
    for hh in _households():
        numbers = [d.fields["id_number"] for d in hh.documents if d.type == "identity_card"]
        assert len(set(numbers)) == len(numbers)
        for n in numbers:
            assert len(n) == 12 and n.isdigit() and n[0] in "01"


def test_every_error_type_is_planted_somewhere() -> None:
    counts = Counter(e.type for hh in _households() for e in hh.planted_errors)
    assert set(counts) == {"name_mismatch", "dob_mismatch", "expired", "missing_document", "not_on_ration_card"}
    assert any(not hh.planted_errors for hh in _households())


def test_planted_errors_are_visible_in_documents() -> None:
    for hh in _households():
        members = {m.id: m for m in hh.members}
        for e in hh.planted_errors:
            m = members[e.member_id]
            if e.type == "name_mismatch":
                d = _doc(hh, e.documents[0])
                assert (d.fields["name_mr"], d.fields["name_en"]) == (e.printed["mr"], e.printed["en"])
                assert e.printed != e.expected == m.full_name.model_dump()
            elif e.type == "dob_mismatch":
                assert _doc(hh, e.documents[0]).fields["dob"] == e.printed != fmt_date(m.dob)
                assert _doc(hh, e.documents[1]).fields["dob"] == fmt_date(m.dob)
            elif e.type == "expired":
                lo, hi = EXPIRED_INCOME_CERT_AGE_DAYS
                assert lo <= _days_old(_doc(hh, e.documents[0]).fields["issue_date"]) <= hi
            elif e.type == "missing_document":
                assert _doc(hh, e.documents[0]) is None
            elif e.type == "not_on_ration_card":
                rows = _doc(hh, "ration_card").fields["members"]
                assert m.full_name.en not in [r["name_en"] for r in rows]
                assert not m.on_ration_card
                assert _doc(hh, f"identity_card_{m.id}") is not None


def test_clean_documents_agree_with_members() -> None:
    for hh in _households():
        erred = {d for e in hh.planted_errors for d in e.documents}
        members = {m.id: m for m in hh.members}
        for d in hh.documents:
            if d.id in erred or d.type == "ration_card":
                continue
            m = members[d.member_ids[0]]
            assert d.fields["name_en"] == m.full_name.en
            if "dob" in d.fields:
                assert d.fields["dob"] == fmt_date(m.dob)
            if d.type == "income_certificate":
                lo, hi = VALID_INCOME_CERT_AGE_DAYS
                assert lo <= _days_old(d.fields["issue_date"]) <= hi


def test_name_variants_differ() -> None:
    pools = {p.en: p for p in N.MALE_NAMES + N.FEMALE_NAMES + N.SURNAMES}
    for key, variant in N.VARIANTS.items():
        assert key in pools, key
        assert variant != pools[key], key


def test_photo_like_is_deterministic() -> None:
    doc = np.full((300, 400, 3), 240, np.uint8)
    cv2.putText(doc, "SPECIMEN", (40, 160), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
    png = cv2.imencode(".png", doc)[1].tobytes()
    a, pa = photo_like(png, np.random.default_rng(7))
    b, pb = photo_like(png, np.random.default_rng(7))
    assert a == b and pa == pb
    out = cv2.imdecode(np.frombuffer(a, np.uint8), cv2.IMREAD_COLOR)
    assert out.shape[0] > 300 and out.shape[1] > 400


def test_render_filters() -> None:
    assert id_groups("012345678901") == "0123 4567 8901"
    assert rupees(120000) == "1,20,000"
    assert rupees(24000) == "24,000"
    assert rupees(999) == "999"


def test_scoring() -> None:
    assert normalize(" सुनील  रमेश, पाटील ") == normalize("सुनील रमेश पाटील")
    assert matches(120000, "Rs. 1,20,000")
    assert matches(35, "३५")
    assert not matches("Sunil", None)
    assert not matches("सुनील", "सुनिल")
    assert matches("स्वतः", "स्वत:")  # visarga misread as ASCII colon
    assert not matches("स्वतः", "स्वत")
    expected = {"name_en": "Sunil Patil", "members": [{"age": 30}, {"age": 5}]}
    correct, total, wrong = score(expected, {"name_en": "sunil patil", "members": [{"age": "30"}]})
    assert (correct, total) == (2, 3)
    assert wrong == [("members[1].age", 5, None)]
