"""After reading: background items dropped, unidentified items kept apart, cut-off documents on the clearer-photo
list, duplicates merged, and the plan mode (none / close_ups / hold)."""

from clients.llm import TokenUsage
from graph.nodes.read_documents import ReadResult
from graph.nodes.triage import CUT_OFF, Seen, triage
from schemas.documents import DocumentExtraction
from tests.test_household import SUNEEL_ID, SUNIL, _card, _doc, _id

RATION = _card(SUNIL)


def _read(ex: DocumentExtraction, *frames: DocumentExtraction) -> ReadResult:
    return ReadResult(extraction=ex, usage=TokenUsage(), elapsed_s=0.0, attempts=1, cached=False,
                      frame_reads=list(frames))


def _blurry(ex: DocumentExtraction, reason: str = "dob missing") -> DocumentExtraction:
    return ex.model_copy(update={"needs_retake": True, "retake_reasons": [reason]})


def _income(doc_id: str, name: str, issued: str, number: str | None = None) -> DocumentExtraction:
    return _doc(doc_id, "income_certificate", name_en=name, annual_income=50000, issue_date=issued,
                certificate_number=number)


UNREAD = DocumentExtraction(document_id="x", unreadable=True, error="frames do not agree")


def test_all_clear() -> None:
    t = triage([Seen("rc"), Seen("id1")], {"rc": _read(RATION), "id1": _read(SUNEEL_ID)})
    assert list(t.extractions) == ["rc", "id1"] and t.plan.mode == "none" and t.plan.read == 2 and not t.dropped


def test_unidentified_items_are_dropped_when_sam_was_unsure_else_listed() -> None:
    other = DocumentExtraction(document_id="x", doc_type="other")
    reads = {"rc": _read(RATION), "bg": _read(UNREAD, other, other), "maybe": _read(UNREAD, other, other)}
    t = triage([Seen("rc"), Seen("bg", score=0.3), Seen("maybe", score=0.95)], reads)
    assert t.dropped == ["bg"]
    assert t.extractions["maybe"].doc_type == "other" and t.plan.unidentified == ["maybe"]
    assert t.plan.mode == "none" and t.plan.read == 1  # an unidentified item is not a document that needs a photo


def test_frames_that_disagree_on_a_known_type_need_a_photo_not_unidentified() -> None:
    disagree = _blurry(DocumentExtraction(document_id="d", unreadable=True), "frames do not agree")
    reads = {"rc": _read(RATION), "d": _read(disagree, _id("d", None, None, None), DocumentExtraction(document_id="d", doc_type="other"))}
    t = triage([Seen("rc"), Seen("d", score=0.2)], reads)
    assert "d" in t.extractions and t.plan.documents == ["d"] and t.plan.mode == "close_ups"


def test_cut_off_documents_are_kept_and_named_when_their_read_is_incomplete() -> None:
    reads = {"rc": _read(RATION), "id1": _read(SUNEEL_ID), "id2": _read(_blurry(_id("id2", None, "Rekha Patil", None, "F", "5555")))}
    t = triage([Seen("rc"), Seen("id1", fully_visible=False), Seen("id2", fully_visible=False)], reads)
    assert not t.extractions["id1"].needs_retake  # complete, agreed read: it stands
    assert t.plan.reasons == {"id2": ["dob missing", CUT_OFF]} and t.plan.mode == "close_ups"


def test_more_than_half_unclear_holds_the_plan() -> None:
    reads = {"rc": _read(_blurry(RATION, "members missing")), "id1": _read(_blurry(SUNEEL_ID)), "id2": _read(_id("id2", None, "Rekha Patil", "01/01/1990", "F", "5555"))}
    t = triage([Seen("rc"), Seen("id1"), Seen("id2")], reads)
    assert t.plan.mode == "hold" and t.plan.documents == ["id1", "rc"] and t.plan.read == 3


def test_duplicates_keep_the_clearer_read() -> None:
    a = _blurry(_income("a", "Sunil Ramesh Patil", "01/04/2025"), "annual_income missing")
    b = _income("b", "Sunil Ramesh Patil", "01/04/2025")
    t = triage([Seen("rc"), Seen("a"), Seen("b")], {"rc": _read(RATION), "a": _read(a), "b": _read(b)})
    assert list(t.extractions) == ["rc", "b"] and t.duplicates == {"a": "b"} and t.plan.mode == "none"


def test_same_certificate_number_is_the_same_document_and_different_people_are_not() -> None:
    a = _income("a", "Sunil Patil", "01/04/2025", "SPEC/INC/1")
    b = _income("b", "Sunil R Patil", None, "SPEC/INC/1")  # name read differently, same number
    c = _income("c", "Rekha Patil", "01/04/2025", "SPEC/INC/2")
    t = triage([Seen("a"), Seen("b"), Seen("c")], {"a": _read(a), "b": _read(b), "c": _read(c)})
    assert sorted(t.extractions) == ["a", "c"] and t.duplicates == {"b": "a"}


def test_three_identity_cards_of_different_people_are_kept() -> None:
    ids = {f"id{i}": _id(f"id{i}", None, name, dob, "F", last4)
           for i, (name, dob, last4) in enumerate([("Lata Bhosale", "28/02/2014", "2598"),
                                                   ("Savita Bhosale", "01/01/1980", "3388"),
                                                   ("Lalita Bhosale", "05/05/1960", "1111")])}
    t = triage([Seen(i) for i in ids], {i: _read(e) for i, e in ids.items()})
    assert sorted(t.extractions) == sorted(ids) and not t.duplicates


def test_a_blurry_second_view_with_only_the_name_is_merged() -> None:
    clear = _income("a", "Sunil Ramesh Patil", "01/04/2025", "SPEC/INC/1")
    blurry = _blurry(_income("b", "Sunil Ramesh Patil", None), "issue_date missing")
    aadhaar_last4_only = _blurry(_id("c", None, None, None, "M", "1234"), "name missing")
    reads = {"a": _read(clear), "b": _read(blurry), "id1": _read(SUNEEL_ID), "c": _read(aadhaar_last4_only)}
    t = triage([Seen("a"), Seen("b"), Seen("id1"), Seen("c")], reads)
    assert t.duplicates == {"b": "a", "c": "id1"} and t.plan.mode == "none"
