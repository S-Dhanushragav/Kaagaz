"""Close-up loop: a clearer photo of one document on the clearer-photo list (or of an item that could not be
identified) replaces its reading, and the graph runs again from build_household (household -> rules -> plan ->
speak).

Only a clear read counts (readable, and every field decisions need is present); otherwise nothing changes and
the family is told which details are still missing. The re-run is a LangGraph state update "as" read_documents,
so the graph continues along its normal edges: while more than half of the documents still need a photo the
plan stays on hold ('hold' ends the run again right away).
"""

from typing import Any, Callable

import cv2
import numpy as np

from graph.nodes.read_documents import DocumentInput, ReadResult, read_document
from graph.runtime import runtime
from schemas.documents import DECISION_FIELDS, DocumentExtraction, field_pattern, null_paths
from vision.images import encode_for_llm
from vision.orient import make_upright

Reader = Callable[[DocumentInput], ReadResult]


class CloseupError(ValueError):
    pass


def missing_fields(extraction: DocumentExtraction) -> list[str]:
    """Why a read is not clear enough: unreadable, not a known document, or decision fields missing."""
    if extraction.unreadable or extraction.fields is None or extraction.doc_type in (None, "other"):
        return ["document"]
    return [p for p in null_paths(extraction.fields) if field_pattern(p) in DECISION_FIELDS[extraction.doc_type]]


def apply_closeup(graph: Any, session_id: str, config: dict[str, Any], document_id: str, photo: bytes,
                  reader: Reader = read_document) -> dict[str, Any]:
    values = graph.get_state(config).values or {}
    recapture = values.get("recapture") or {}
    waiting = [*recapture.get("documents", []), *recapture.get("unidentified", [])]
    if recapture.get("mode") not in ("close_ups", "hold") or document_id not in waiting:
        raise CloseupError("This document is not waiting for a close-up.")
    image = cv2.imdecode(np.frombuffer(photo, dtype=np.uint8), cv2.IMREAD_COLOR)  # applies EXIF rotation
    if image is None:
        raise CloseupError("The photo could not be opened.")
    image, _ = make_upright(image)  # a photo taken sideways is read the right way up
    jpeg = encode_for_llm(image)
    read = reader(DocumentInput(id=document_id, images=[jpeg]))
    missing = missing_fields(read.extraction)
    if missing:
        return {"clear": False, "missing": missing}
    extractions = [e for e in values.get("extractions", []) if e["document_id"] != document_id]
    extractions.append(read.extraction.model_dump(mode="json"))
    remaining = [d for d in recapture.get("documents", []) if d != document_id]
    unidentified = [d for d in recapture.get("unidentified", []) if d != document_id]
    read_count = recapture.get("read", len(extractions)) + (1 if document_id in recapture.get("unidentified", []) else 0)
    mode = "none" if not remaining else "hold" if len(remaining) > read_count / 2 else "close_ups"
    runtime(session_id).add_document(document_id, [jpeg])  # the name verifier re-reads this photo
    graph.update_state(config, {
        "extractions": extractions,
        "recapture": {"mode": mode, "documents": remaining, "unidentified": unidentified, "read": read_count,
                      "reasons": {d: r for d, r in recapture.get("reasons", {}).items() if d in remaining}},
        "usage": {"read_tokens": read.usage.prompt_tokens + read.usage.completion_tokens},
        "log": [f"close-up of {document_id} read clearly"],
    }, as_node="read_documents")
    return {"clear": True, "missing": []}
