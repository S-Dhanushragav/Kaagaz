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
