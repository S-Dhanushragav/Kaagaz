"""After reading: which documents were read clearly, which need a clearer photo, and which items to drop.

Deterministic (no model call). For each found document, in order:
1. Not read as any known type by any read: if SAM was unsure it was a document at all (low score), drop it;
   otherwise keep it as 'unidentified' (doc_type 'other'), so the app can say one more item could not be read.
2. Cut off by the frame edge in every frame: kept, and named on the clearer-photo list if its read is missing
   something (CUT_OFF added to the reasons). A complete read stands: the frames that read it agreed on every
   decision field. Measured on a real phone video (Phase 9c): documents filling the phone's width touch the edge
   in every frame, and all 4 of them read every key field correctly; the finder used to drop them unread.
3. The same document found twice (shown twice, or seen again after the camera moved on): keep the better read.
   Two reads are the same document when they share an identifying detail (see `_identity_keys`).
Then the recapture plan (graph/nodes/find_documents.py `plan_recapture`).
"""

from dataclasses import dataclass
from typing import Mapping, Sequence

from graph.nodes.find_documents import FindResult, RecapturePlan, recapture_plan
from graph.nodes.read_documents import ReadResult
from schemas.documents import DECISION_FIELDS, DocumentExtraction, field_pattern, null_paths
from vision.text import comparison_key

LOW_SAM_SCORE = 0.6  # below this an unreadable item is treated as background, not as a document
CUT_OFF = "cut off at the edge of the picture"


@dataclass(frozen=True)
class Seen:
    """What the finder knows about one document: its id, whether it was ever fully in view, SAM's confidence."""

    id: str
    fully_visible: bool = True
    score: float | None = None


@dataclass
class Triage:
    extractions: dict[str, DocumentExtraction]  # kept documents, in finder order
    plan: RecapturePlan
    dropped: list[str]  # removed: background items and duplicates
    duplicates: dict[str, str]  # dropped id -> the id kept in its place


def identified(read: ReadResult) -> bool:
    """Any read (of any frame) saw one of the four document types."""
    reads = read.frame_reads or [read.extraction]
    return any(not e.unreadable and e.doc_type not in (None, "other") for e in reads + [read.extraction])


def _key(value: object) -> str | None:
    if value is None:
        return None
    k = comparison_key(value)
    return k if len(k) >= 3 else None


def _identity_keys(ex: DocumentExtraction) -> set[str]:
    """Details that identify one physical document; two reads sharing any of them are the same document."""
    if ex.fields is None or ex.doc_type in (None, "other"):
        return set()
    f = ex.fields.model_dump()
    t = ex.doc_type
    names = [n for n in (_key(f.get("name_en")), _key(f.get("name_mr"))) if n]
    # One person rarely has two documents of the same type, so the same type and name is the same document (a blurry
    # second view often has the name but not the dates).
    keys: set[str] = {f"{t}:name:{n}" for n in names}
    if t == "ration_card":
        number = _key(f.get("card_number"))
        if number:
            keys.add(f"{t}:no:{number}")
        keys |= {f"{t}:head:{n}" for n in (_key(f.get("head_name_en")), _key(f.get("head_name_mr"))) if n}
    elif t == "identity_card":
        dob, last4 = _key(f.get("dob")), _key(f.get("id_number"))
        if last4:
            keys.add(f"{t}:id:{last4}")
    else:  # income and caste certificates
        number = _key(f.get("certificate_number"))
        if number:
            keys.add(f"{t}:no:{number}")
    return keys


def _quality(ex: DocumentExtraction, seen: Seen) -> tuple[int, int, int]:
    """Higher is better: clear, fully in view, fewer missing decision fields."""
    missing = 99
    if ex.fields is not None and ex.doc_type in DECISION_FIELDS:
        missing = sum(1 for p in null_paths(ex.fields) if field_pattern(p) in DECISION_FIELDS[ex.doc_type])
    return (0 if ex.needs_retake or ex.unreadable else 1, 1 if seen.fully_visible else 0, -missing)


def triage(seen: Sequence[Seen], reads: Mapping[str, ReadResult]) -> Triage:
    extractions: dict[str, DocumentExtraction] = {}
    dropped: list[str] = []
    for s in seen:
        read = reads.get(s.id)
        if read is None:
            continue
        ex = read.extraction
        if not identified(read):
            if s.score is not None and s.score < LOW_SAM_SCORE:
                dropped.append(s.id)
                continue
            ex = DocumentExtraction(document_id=s.id, doc_type="other", error=ex.error)
        elif not s.fully_visible and ex.needs_retake:
            ex = ex.model_copy(update={"retake_reasons": [*ex.retake_reasons, CUT_OFF]})
        extractions[s.id] = ex

    # Same document read more than once: keep the best read of each group (groups joined by shared keys).
    by_id = {s.id: s for s in seen}
    owner: dict[str, str] = {}  # identity key -> the kept document id
    duplicates: dict[str, str] = {}
    for doc_id in list(extractions):
        ex = extractions[doc_id]
        keys = _identity_keys(ex)
        match = next((owner[k] for k in keys if k in owner and owner[k] in extractions), None)
        if match is None:
            owner.update({k: doc_id for k in keys})
            continue
        kept, other = (doc_id, match) if _quality(ex, by_id[doc_id]) > _quality(extractions[match], by_id[match]) \
            else (match, doc_id)
        duplicates[other] = kept
        owner.update({k: kept for k in keys | _identity_keys(extractions[other])})
        del extractions[other]
    dropped += list(duplicates)

    return Triage(extractions=extractions, plan=recapture_plan(list(extractions), extractions), dropped=dropped,
                  duplicates=duplicates)


def seen_from(result: FindResult) -> list[Seen]:
    return [Seen(d.document.id, d.fully_visible, d.score) for d in result.documents]
