"""Reader tests with a fake LLM client: no network, no cache."""

import json
import threading
import time
from typing import Any

from clients.llm import LLMError, LLMResponse, TokenUsage
from graph.nodes.read_documents import DocumentInput, read_document, read_documents
from schemas.documents import IdentityCardFields

GOOD = {
    "doc_type": "identity_card",
    "fields": {
        "name_mr": "सुनील रमेश पाटील", "name_en": "Sunil Ramesh Patil", "dob": "05/03/1990",
        "gender_mr": "पुरुष", "gender_en": "Male", "id_number": "XXXX XXXX 8901",
    },
}
DOC = DocumentInput(id="HH001/identity_card_m1", images=[b"jpeg"])


class FakeLLM:
    """Returns scripted replies in order, applying `redact` like the real client, and records calls."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, prompt: str, **kwargs: Any) -> LLMResponse:
        self.calls.append({"prompt": prompt, **kwargs})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        if kwargs.get("redact"):
            text = kwargs["redact"](text)
        return LLMResponse(text=text, task="vision", provider="fake", model="fake",
                           usage=TokenUsage(prompt_tokens=100, completion_tokens=10, total_tokens=110))


def with_fields(**changes: Any) -> dict[str, Any]:
    return {**GOOD, "fields": {**GOOD["fields"], **changes}}


def test_success_first_try() -> None:
    llm = FakeLLM(GOOD)
    r = read_document(DOC, llm=llm)
    assert r.attempts == 1 and not r.extraction.unreadable
    assert r.extraction.doc_type == "identity_card"
    assert isinstance(r.extraction.fields, IdentityCardFields)
    assert r.usage.completion_tokens == 10
    call = llm.calls[0]
    assert call["task"] == "vision" and call["images"] == [b"jpeg"]
    assert call["response_format"]["type"] == "json_schema"


def test_wrapped_reply_is_unwrapped() -> None:
    r = read_document(DOC, llm=FakeLLM({"document": GOOD}))
    assert r.attempts == 1 and r.extraction.doc_type == "identity_card"


def test_text_is_normalized_and_nulls_reported() -> None:
    r = read_document(DOC, llm=FakeLLM(with_fields(name_mr="स्वत:", gender_en=None)))
    assert r.extraction.fields.name_mr == "स्वतः"
    assert r.extraction.unreadable_fields == ["gender_en"]


def test_full_identity_number_never_reaches_caller() -> None:
    for raw in ("012345678901", "0123 4567 8901", "0123-4567-8901"):
        r = read_document(DOC, llm=FakeLLM(with_fields(id_number=raw)))
        assert r.extraction.fields.id_number == "XXXX XXXX 8901"
        assert "0123" not in r.extraction.model_dump_json()


def test_retry_after_validation_error_then_success() -> None:
    llm = FakeLLM(with_fields(dob="1990-03-05"), GOOD)
    r = read_document(DOC, llm=llm)
    assert r.attempts == 2 and not r.extraction.unreadable
    assert r.usage.completion_tokens == 20
    retry_prompt = llm.calls[1]["prompt"]
    assert "dob" in retry_prompt and "1990-03-05" in retry_prompt  # error and previous reply included
    assert "return null" in retry_prompt
    assert "Never change a value just to pass validation" in retry_prompt


def test_retry_after_non_json_reply() -> None:
    llm = FakeLLM("sorry, I cannot read this", GOOD)
    r = read_document(DOC, llm=llm)
    assert r.attempts == 2 and not r.extraction.unreadable
    assert "not a JSON object" in llm.calls[1]["prompt"] or "not valid JSON" in llm.calls[1]["prompt"]


def test_two_failures_mark_unreadable() -> None:
    r = read_document(DOC, llm=FakeLLM(with_fields(dob="bad"), with_fields(dob="still bad")))
    assert r.attempts == 2
    assert r.extraction.unreadable and r.extraction.fields is None
    assert "dob" in r.extraction.error


def test_llm_error_marks_unreadable_without_retry() -> None:
    r = read_document(DOC, llm=FakeLLM(LLMError("hit max_tokens")))
    assert r.attempts == 1 and r.extraction.unreadable
    assert "max_tokens" in r.extraction.error


def test_unknown_doc_type_triggers_retry() -> None:
    llm = FakeLLM({"doc_type": "passport", "fields": None}, GOOD)
    assert read_document(DOC, llm=llm).attempts == 2


def test_other_document_has_no_fields() -> None:
    r = read_document(DOC, llm=FakeLLM({"doc_type": "other", "fields": None}))
    assert r.extraction.doc_type == "other" and r.extraction.fields is None and not r.extraction.unreadable


def test_parallel_keeps_order_and_limits_concurrency() -> None:
    lock, active, peak = threading.Lock(), [0], [0]

    def slow_llm(prompt: str, **kwargs: Any) -> LLMResponse:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return FakeLLM(GOOD)(prompt, **kwargs)

    docs = [DocumentInput(id=f"d{i}", images=[b"x"]) for i in range(10)]
    results = read_documents(docs, llm=slow_llm, max_workers=4)
    assert [r.extraction.document_id for r in results] == [f"d{i}" for i in range(10)]
    assert peak[0] <= 4


def test_document_input_takes_one_to_three_images() -> None:
    import pytest
    from pydantic import ValidationError

    DocumentInput(id="a", images=[b"1", b"2", b"3"])
    with pytest.raises(ValidationError):
        DocumentInput(id="a", images=[])
    with pytest.raises(ValidationError):
        DocumentInput(id="a", images=[b"1", b"2", b"3", b"4"])


# ---------- frame agreement (video crops: one read per frame) ----------

from graph.nodes.read_documents import StreamingReader, agree_extractions  # noqa: E402
from schemas.documents import DocumentExtraction, IncomeCertificateFields  # noqa: E402


def _id_frame(**changes: Any) -> DocumentExtraction:
    return DocumentExtraction(document_id="f", doc_type="identity_card",
                              fields=IdentityCardFields(**{**GOOD["fields"], **changes}))


def test_agreement_keeps_values_two_frames_share() -> None:
    frames = [
        _id_frame(name_en="Sunil Ramesh Patil", dob="05/03/1990"),
        _id_frame(name_en="Sunil  Ramesh patil", dob="06/03/1990"),  # same name after normalization
        _id_frame(name_en="Suneel Ramesh Patil", dob="08/03/1990"),
    ]
    ex = agree_extractions("doc01", frames)
    assert ex.document_id == "doc01" and ex.doc_type == "identity_card"
    assert ex.fields.name_en == "Sunil Ramesh Patil"  # 2 of 3 agree; value from the best frame
    assert ex.fields.dob is None and "dob" in ex.disagreed_fields  # all three differ
    assert ex.needs_retake and "dob missing" in ex.retake_reasons


def test_agreement_display_fields_come_from_best_frame() -> None:
    base = {"certificate_number": "SPEC/INC/1", "name_mr": "अ", "name_en": "A", "address_mr": "प",
            "annual_income": 120000, "financial_year": "2025-26", "issue_date": "01/10/2026",
            "office_mr": "क", "office_en": "O"}
    frames = [DocumentExtraction(document_id="f", doc_type="income_certificate",
                                 fields=IncomeCertificateFields(**base, address_en=addr))
              for addr in ("House 1, Namunapur", "House 7, Namunapur")]
    ex = agree_extractions("doc02", frames)
    assert ex.fields.address_en == "House 1, Namunapur"  # display-only: single read, best frame
    assert ex.fields.annual_income == 120000 and not ex.needs_retake


def test_agreement_needs_two_frames() -> None:
    ex = agree_extractions("doc03", [_id_frame()])
    assert ex.unreadable and ex.needs_retake and ex.fields is None


def test_agreement_on_document_type() -> None:
    other = DocumentExtraction(document_id="f", doc_type="other")
    ex = agree_extractions("doc04", [_id_frame(), other])
    assert ex.unreadable and ex.needs_retake and "type" in ex.error
    ex = agree_extractions("doc05", [_id_frame(), other, _id_frame()])  # 2 of 3 say identity_card
    assert ex.doc_type == "identity_card" and not ex.needs_retake


def test_agreement_ignores_unreadable_frames() -> None:
    bad = DocumentExtraction(document_id="f", unreadable=True, error="x")
    ex = agree_extractions("doc06", [_id_frame(), bad, _id_frame()])
    assert ex.doc_type == "identity_card" and ex.fields.dob == "05/03/1990"


def test_agreement_on_ration_card_member_rows() -> None:
    row = {"name_mr": "अ", "name_en": "Anil", "relation_mr": "र", "relation_en": "Son",
           "gender_mr": "पुरुष", "gender_en": "Male", "age": 9}
    card = {"card_number": "1", "card_colour": "orange", "category_mr": "प", "category_en": "PHH", "head_name_mr": "ह",
            "head_name_en": "Head", "address_mr": None, "address_en": None}

    def frame(name: str) -> DocumentExtraction:
        return DocumentExtraction(document_id="f", doc_type="ration_card",
                                  fields={**card, "members": [row, {**row, "name_en": name}]})

    ex = agree_extractions("doc07", [frame("Rekha"), frame("Ravita")])
    assert ex.fields.members[0].name_en == "Anil" and ex.fields.members[1].name_en is None
    assert ex.fields.members[1].name_mr == "अ"  # Marathi name still agreed: key group satisfied
    assert not ex.needs_retake


def test_streaming_reader_reads_each_frame_and_agrees() -> None:
    replies = {b"f1": with_fields(dob="05/03/1990"), b"f2": with_fields(dob="05/03/1990"),
               b"f3": with_fields(dob="09/09/1999")}

    def llm(prompt: str, **kwargs: Any) -> LLMResponse:
        (img,) = kwargs["images"]  # one frame per call
        return FakeLLM(replies[img])(prompt, **kwargs)

    with StreamingReader(llm=llm, agreement=True) as reader:
        reader.submit(DocumentInput(id="doc01", images=[b"f1", b"f2", b"f3"]))
        results = reader.results()
    r = results["doc01"]
    assert r.extraction.fields.dob == "05/03/1990" and not r.extraction.needs_retake
    assert len(r.frame_reads) == 3 and r.usage.completion_tokens == 30


def test_read_documents_without_agreement_reads_all_images_together() -> None:
    llm = FakeLLM(GOOD)
    (r,) = read_documents([DocumentInput(id="d", images=[b"a", b"b"])], llm=llm)
    assert llm.calls[0]["images"] == [b"a", b"b"] and r.attempts == 1


def test_agreement_strength_from_frame_times() -> None:
    frames = [_id_frame(), _id_frame(), _id_frame()]
    assert agree_extractions("d", frames, times_s=[1.0, 1.2, 1.6]).agreement_strength == "strong"  # 0.6 s
    weak = agree_extractions("d", frames[:2], times_s=[1.0, 1.2])
    assert weak.agreement_strength == "weak" and weak.agreement_gap_s == 0.2
    assert agree_extractions("d", frames[:2]).agreement_strength is None  # no times known
    # only the frames that agreed on the type count
    other = DocumentExtraction(document_id="f", doc_type="other")
    ex = agree_extractions("d", [_id_frame(), other, _id_frame()], times_s=[1.0, 3.0, 1.3])
    assert ex.agreement_gap_s == 0.3 and ex.agreement_strength == "weak"


def test_streaming_reader_reports_finished_documents_without_waiting() -> None:
    release = threading.Event()

    def llm(prompt: str, **kwargs: Any) -> LLMResponse:
        if kwargs["images"] == [b"slow"]:
            release.wait(5)
        return FakeLLM(GOOD)(prompt, **kwargs)

    with StreamingReader(llm=llm, agreement=False) as reader:
        reader.submit(DocumentInput(id="fast", images=[b"fast"]))
        reader.submit(DocumentInput(id="slow", images=[b"slow"]))
        deadline = time.time() + 5
        while "fast" not in reader.done() and time.time() < deadline:
            time.sleep(0.01)
        assert set(reader.done()) == {"fast"}  # the slow one is still being read
        release.set()
        assert set(reader.results()) == {"fast", "slow"}
