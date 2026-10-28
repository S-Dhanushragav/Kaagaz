"""Document reader: classify + extract each document in one structured-output LLM call.

Plain function for now; it becomes a LangGraph node later. Per document:
call -> parse JSON -> normalize text -> validate (Pydantic). On a parse/validation error,
retry once with the errors; if that fails too, the document is marked unreadable.
Identity numbers are masked by the LLM client before the reply is cached or returned.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping

from openai import APIError
from pydantic import BaseModel, Field, ValidationError

from clients.llm import LLMError, LLMResponse, TokenUsage, complete
from schemas.documents import FIELD_MODELS, DocumentExtraction, null_paths, reply_json_schema
from vision.text import normalize_text, redact_identity_numbers

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
EXTRACT_PROMPT = (PROMPTS / "extract.md").read_text(encoding="utf-8")
RETRY_PROMPT = (PROMPTS / "extract_retry.md").read_text(encoding="utf-8")

RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {"name": "document_extraction", "strict": True, "schema": reply_json_schema()},
}
MAX_PARALLEL = 4

LLM = Callable[..., LLMResponse]


class DocumentInput(BaseModel):
    id: str
    images: list[bytes] = Field(min_length=1, max_length=3)  # prepared JPEGs of one document


class ReadResult(BaseModel):
    extraction: DocumentExtraction
    usage: TokenUsage  # summed over attempts
    elapsed_s: float
    attempts: int
    cached: bool  # every attempt was served from the cache


class _ReplyError(ValueError):
    pass


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return normalize_text(value).strip()
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _format_errors(e: ValidationError) -> str:
    return "\n".join(
        f"- {'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']} (got {err.get('input')!r})"
        for err in e.errors()
    )


def parse_reply(document_id: str, text: str) -> DocumentExtraction:
    """Parse and validate one model reply. Raises _ReplyError with a message fit for the retry prompt."""
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start : end + 1]) if 0 <= start < end else None
    except json.JSONDecodeError as e:
        raise _ReplyError(f"- reply is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise _ReplyError("- reply is not a JSON object")
    data = _normalize(data)

    doc_type, raw_fields = data.get("doc_type"), data.get("fields")
    if doc_type not in (*FIELD_MODELS, "other"):
        raise _ReplyError(f"- doc_type: must be one of {', '.join([*FIELD_MODELS, 'other'])} (got {doc_type!r})")
    if doc_type == "other":
        return DocumentExtraction(document_id=document_id, doc_type="other")
    if not isinstance(raw_fields, dict):
        raise _ReplyError(f"- fields: must be an object for doc_type {doc_type} (got {raw_fields!r})")
    try:
        fields = FIELD_MODELS[doc_type].model_validate(raw_fields)
    except ValidationError as e:
        raise _ReplyError(_format_errors(e)) from None
    return DocumentExtraction(
        document_id=document_id,
        doc_type=doc_type,
        fields=fields,
        unreadable_fields=list(null_paths(fields)),
    )


def read_document(doc: DocumentInput, *, overrides: Mapping[str, Any] | None = None, llm: LLM = complete) -> ReadResult:
    start = time.perf_counter()
    usage = TokenUsage()
    attempts = 0
    all_cached = True

    def call(prompt: str) -> str:
        nonlocal attempts, all_cached
        attempts += 1
        resp = llm(
            prompt,
            task="vision",
            images=doc.images,
            response_format=RESPONSE_FORMAT,
            overrides=overrides,
            redact=redact_identity_numbers,
        )
        usage.prompt_tokens += resp.usage.prompt_tokens
        usage.completion_tokens += resp.usage.completion_tokens
        usage.total_tokens += resp.usage.total_tokens
        all_cached = all_cached and resp.cached
        return resp.text

    def done(extraction: DocumentExtraction) -> ReadResult:
        return ReadResult(
            extraction=extraction, usage=usage, elapsed_s=time.perf_counter() - start,
            attempts=attempts, cached=all_cached and attempts > 0,
        )

    def unreadable(error: str) -> ReadResult:
        return done(DocumentExtraction(document_id=doc.id, unreadable=True, error=error))

    try:
        reply = call(EXTRACT_PROMPT)
        try:
            return done(parse_reply(doc.id, reply))
        except _ReplyError as first:
            retry = EXTRACT_PROMPT + RETRY_PROMPT.replace("{previous}", reply).replace("{errors}", str(first))
            reply = call(retry)
            try:
                return done(parse_reply(doc.id, reply))
            except _ReplyError as second:
                return unreadable(f"invalid after retry:\n{second}")
    except (LLMError, APIError) as e:
        return unreadable(f"LLM call failed: {e}")


def read_documents(
    docs: list[DocumentInput],
    *,
    overrides: Mapping[str, Any] | None = None,
    llm: LLM = complete,
    max_workers: int = MAX_PARALLEL,
) -> list[ReadResult]:
    """Read documents in parallel (at most `max_workers` at once); results keep input order."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(lambda d: read_document(d, overrides=overrides, llm=llm), docs))
