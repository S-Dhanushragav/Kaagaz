"""Document reader: classify + extract each document in one structured-output LLM call.

Plain function for now; it becomes a LangGraph node later. Per call:
call -> parse JSON -> normalize text -> validate (Pydantic). On a parse/validation error,
retry once with the errors; if that fails too, the document is marked unreadable.
Identity numbers are masked by the LLM client before the reply is cached or returned.

For video crops (2-3 frames per document), each frame is read separately and decision fields
(names, dates, gender, ID last 4, income, category) are kept only where frames agree; see
`agree_extractions`. Documents start reading as soon as they are submitted (`StreamingReader`).
"""

import json
import re
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from openai import APIError
from pydantic import BaseModel, Field, ValidationError

from clients.llm import LLMError, LLMResponse, TokenUsage, complete
from schemas.documents import (
    DECISION_FIELDS,
    FIELD_MODELS,
    KEY_FIELDS,
    DocumentExtraction,
    field_pattern,
    null_paths,
    reply_json_schema,
)
from vision.text import comparison_key, normalize_text, redact_identity_numbers

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
EXTRACT_PROMPT = (PROMPTS / "extract.md").read_text(encoding="utf-8")
RETRY_PROMPT = (PROMPTS / "extract_retry.md").read_text(encoding="utf-8")

RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {"name": "document_extraction", "strict": True, "schema": reply_json_schema()},
}
MAX_PARALLEL = 8

LLM = Callable[..., LLMResponse]


class DocumentInput(BaseModel):
    id: str
    images: list[bytes] = Field(min_length=1, max_length=3)  # prepared JPEGs of one document
    frame_times_s: list[float] | None = None  # capture time of each image (video crops), for agreement strength


class ReadResult(BaseModel):
    extraction: DocumentExtraction
    usage: TokenUsage  # summed over attempts (and frames, with agreement)
    elapsed_s: float
    attempts: int
    cached: bool  # every attempt was served from the cache
    frame_reads: list[DocumentExtraction] = []  # per-frame extractions, with agreement


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
    if isinstance(data.get("document"), dict):  # structured-output wrapper, see reply_json_schema()
        data = data["document"]
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
    agreement: bool = False,
) -> list[ReadResult]:
    """Read documents in parallel (at most `max_workers` model calls at once); results keep input order.

    agreement=True reads each image of a document separately and keeps decision fields only where
    at least 2 frames agree (see `agree_extractions`). Use it for video crops, not single photos.
    """
    with StreamingReader(overrides=overrides, llm=llm, max_workers=max_workers, agreement=agreement) as reader:
        for d in docs:
            reader.submit(d)
        results = reader.results()
    return [results[d.id] for d in docs]


# ---------- frame agreement ----------

def _flatten(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _flatten(v, f"{prefix}[{i}]")
    else:
        yield prefix, value


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    node: Any = data
    for part in parts[:-1]:
        node = node[int(part[1:-1])] if part.startswith("[") else node[part]
    last = parts[-1]
    if last.startswith("["):
        node[int(last[1:-1])] = value
    else:
        node[last] = value


def _agreed_value(values: list[Any], min_agree: int) -> tuple[Any, bool]:
    """(value, agreed): the value at least `min_agree` frames share after normalization, else None."""
    groups: dict[str, list[Any]] = {}
    for v in values:
        if v is not None:
            groups.setdefault(comparison_key(v), []).append(v)
    best = max(groups.values(), key=len, default=[])
    return (best[0], True) if len(best) >= min_agree else (None, False)


def _retake_reasons(doc_type: str, fields: Any) -> list[str]:
    flat = dict(_flatten(fields.model_dump()))
    reasons = []
    for group in KEY_FIELDS[doc_type]:
        if group[0].startswith("members."):
            rows = fields.model_dump()["members"]
            keys = [g.split(".", 1)[1] for g in group]
            if not rows or any(all(row.get(k) is None for k in keys) for row in rows):
                reasons.append(f"{'/'.join(group)} missing")
        elif all(flat.get(k) is None for k in group):
            reasons.append(f"{'/'.join(group)} missing")
    return reasons


STRONG_AGREEMENT_GAP_S = 0.5


def agree_extractions(
    document_id: str,
    frames: list[DocumentExtraction],
    min_agree: int = 2,
    times_s: list[float] | None = None,
) -> DocumentExtraction:
    """Combine per-frame reads of one document (best frame first).

    The document type needs `min_agree` frames. Decision fields (DECISION_FIELDS) keep a value only if
    `min_agree` frames agree after normalization; display-only fields come from the best frame that
    has the agreed type. needs_retake is set when key fields (KEY_FIELDS) end up null.
    `times_s` (capture time per frame) gives agreement_gap_s: the time spanned by the frames that
    agreed on the type; 'strong' if >= 0.5 s, else 'weak'.
    """
    readable = [(i, e) for i, e in enumerate(frames) if not e.unreadable and e.doc_type is not None]
    types = Counter(e.doc_type for _, e in readable)
    doc_type, votes = types.most_common(1)[0] if types else (None, 0)
    if doc_type is None or votes < min_agree:
        why = (f"only {len(frames)} frame(s); need {min_agree} that agree" if len(frames) < min_agree
               else f"frames do not agree on the document type ({dict(types) or 'none readable'})")
        return DocumentExtraction(document_id=document_id, unreadable=True, error=why,
                                  needs_retake=True, retake_reasons=[why])
    agreeing = [i for i, e in readable if e.doc_type == doc_type]
    gap, strength = None, None
    if times_s is not None and len(times_s) == len(frames):
        spanned = [times_s[i] for i in agreeing]
        gap = round(max(spanned) - min(spanned), 3)
        strength = "strong" if gap >= STRONG_AGREEMENT_GAP_S else "weak"
    if doc_type == "other":
        return DocumentExtraction(document_id=document_id, doc_type="other",
                                  agreement_gap_s=gap, agreement_strength=strength)

    same = [frames[i] for i in agreeing]
    per_frame = [dict(_flatten(e.fields.model_dump())) for e in same]
    data = same[0].fields.model_dump()
    disagreed = []
    for path, _ in _flatten(data):
        if field_pattern(path) not in DECISION_FIELDS[doc_type]:
            continue
        value, agreed = _agreed_value([f.get(path) for f in per_frame], min_agree)
        if not agreed and any(f.get(path) is not None for f in per_frame):
            disagreed.append(path)
        _set_path(data, path, value)

    fields = FIELD_MODELS[doc_type].model_validate(data)
    reasons = _retake_reasons(doc_type, fields)
    return DocumentExtraction(
        document_id=document_id, doc_type=doc_type, fields=fields,
        unreadable_fields=list(null_paths(fields)), disagreed_fields=disagreed,
        agreement_gap_s=gap, agreement_strength=strength,
        needs_retake=bool(reasons), retake_reasons=reasons,
    )


def _sum_usage(results: list[ReadResult]) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=sum(r.usage.prompt_tokens for r in results),
        completion_tokens=sum(r.usage.completion_tokens for r in results),
        total_tokens=sum(r.usage.total_tokens for r in results),
    )


class StreamingReader:
    """Starts reading each document as soon as it is submitted (e.g. as the finder produces it).

    Model calls run on one pool (`max_workers` at once). With agreement, each image of a document is
    a separate call, and a lightweight coordinator per document combines the frame reads.
    """

    def __init__(self, *, overrides: Mapping[str, Any] | None = None, llm: LLM = complete,
                 max_workers: int = MAX_PARALLEL, agreement: bool = True) -> None:
        self.overrides, self.llm, self.agreement = overrides, llm, agreement
        self._calls = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="read-call")
        self._docs = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="read-doc")
        self._futures: dict[str, Future[ReadResult]] = {}

    def __enter__(self) -> "StreamingReader":
        return self

    def __exit__(self, *exc: object) -> None:
        self._docs.shutdown(wait=True)
        self._calls.shutdown(wait=True)

    def _read_one(self, doc: DocumentInput) -> ReadResult:
        return read_document(doc, overrides=self.overrides, llm=self.llm)

    def _read_agreed(self, doc: DocumentInput) -> ReadResult:
        start = time.perf_counter()
        singles = [DocumentInput(id=f"{doc.id}#f{i + 1}", images=[img]) for i, img in enumerate(doc.images)]
        frame_results = [f.result() for f in [self._calls.submit(self._read_one, s) for s in singles]]
        return ReadResult(
            extraction=agree_extractions(doc.id, [r.extraction for r in frame_results], times_s=doc.frame_times_s),
            usage=_sum_usage(frame_results),
            elapsed_s=time.perf_counter() - start,
            attempts=sum(r.attempts for r in frame_results),
            cached=all(r.cached for r in frame_results),
            frame_reads=[r.extraction for r in frame_results],
        )

    def submit(self, doc: DocumentInput) -> None:
        if self.agreement:
            self._futures[doc.id] = self._docs.submit(self._read_agreed, doc)
        else:
            self._futures[doc.id] = self._calls.submit(self._read_one, doc)

    def results(self) -> dict[str, ReadResult]:
        return {doc_id: f.result() for doc_id, f in self._futures.items()}
