"""Document finder for photos: each photo -> SAM (one photo may hold several documents) -> upright crops.

Per photo, in parallel: decode (EXIF orientation applied; the browser already stripped the rest of EXIF) ->
segment a copy at most SEGMENT_LONG_SIDE px long (smaller upload) -> keep detections that are big enough, drop
near-identical boxes -> mask -> 4 corners -> upright crop from the full photo (vision/deskew.py, same as video).
A photo where SAM finds nothing is read whole (a close-up that fills the frame).

A photo gives one view of each document, so each document carries two images for two independent reads: the
crop and a contrast-evened copy (vision/images.py `second_read_variant`). The streaming reader's agreement then
works as for video frames: decision fields count only where both reads agree, and disagreements put the document
on the clearer-photo list. The same document in several photos is merged after reading (graph/nodes/triage.py).
Photos are deleted after the run by the caller; nothing here writes them anywhere.
"""

import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Sequence

import cv2
import numpy as np

from clients.segmenter import ImageSegmenter, Track, decode_mask_spec
from graph.nodes.find_documents import FindResult, FoundDocument
from graph.nodes.read_documents import DocumentInput
from vision.deskew import deskew
from vision.images import encode_for_llm, read_image, second_read_variant
from vision.orient import make_upright
from vision.tracks import box_area, box_iou

SEGMENT_LONG_SIDE = 1280
MIN_AREA_FRAC = 0.02  # a document smaller than 2% of the photo is too small to read
DUPLICATE_IOU = 0.85
PARALLEL_PHOTOS = 4


def _detections(tracks: list[Track], size: tuple[int, int]) -> list[Track]:
    """Big enough, most confident first, without near-identical boxes."""
    area = size[0] * size[1]
    out: list[Track] = []
    ranked = sorted(tracks, key=lambda t: -(t.frames[0].score or 0)) if tracks else []
    for t in ranked:
        tf = t.frames.get(0)
        if tf is None or box_area(tf.box) < MIN_AREA_FRAC * area:
            continue
        if any(box_iou(tf.box, k.frames[0].box) >= DUPLICATE_IOU for k in out):
            continue
        out.append(t)
    return out


def _document(doc_id: str, crop: np.ndarray, score: float | None, method: str, quad: list[list[float]]) -> FoundDocument:
    images = [encode_for_llm(crop), encode_for_llm(second_read_variant(crop))]
    return FoundDocument(document=DocumentInput(id=doc_id, images=images), track_id=doc_id, source_frames=[],
                         quads=[quad], methods=[method], sharpness=[], fully_visible=True, score=score)


def find_in_photos(
    photos: Sequence[Path],
    *,
    segmenter: ImageSegmenter,
    on_document: Callable[[FoundDocument], None] | None = None,
) -> FindResult:
    """Documents in the photos, as FindResult (same shape as the video finder). Each photo's documents are handed to
    `on_document` as soon as that photo is done; ids are doc<photo><letter> (doc01a, doc01b, doc02a, ...)."""
    start = time.perf_counter()
    seg_seconds: list[float] = []
    lock = threading.Lock()

    def one(index: int, path: Path) -> list[FoundDocument]:
        image = read_image(path)  # cv2.imdecode applies the EXIF orientation
        h, w = image.shape[:2]
        scale = min(1.0, SEGMENT_LONG_SIDE / max(h, w))
        small = cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise ValueError(f"cannot encode {path.name}")
        seg = segmenter.segment_image(buf.tobytes(), (small.shape[1], small.shape[0]))
        seg_seconds.append(seg.timings.get("segment_s", 0.0))
        crops = []
        found = [t.frames[0] for t in _detections(seg.tracks, seg.frame_size)]
        # SAM masks are decoded in worker processes (Meta's decoder is pure Python: threads would take turns).
        pending = [decoders.submit(decode_mask_spec, tf.mask_spec) if tf.mask_spec is not None else None for tf in found]
        for tf, fut in zip(found, pending):
            try:
                res = deskew(image, fut.result() if fut is not None else tf.mask())
            except ValueError:
                continue
            crops.append((res.crop, tf.score, res.method, np.round(res.quad, 1).tolist()))
        if not crops:  # nothing found: the photo itself is the document (a close-up)
            upright, _ = make_upright(image)
            crops.append((upright, None, "whole_photo", [[0, 0], [w, 0], [w, h], [0, h]]))
        docs = [_document(f"doc{index + 1:02d}{chr(ord('a') + k)}", *c) for k, c in enumerate(crops)]
        if on_document is not None:
            with lock:
                for d in docs:
                    on_document(d)
        return docs

    with ProcessPoolExecutor(max_workers=min(PARALLEL_PHOTOS, os.cpu_count() or 2)) as decoders,             ThreadPoolExecutor(max_workers=PARALLEL_PHOTOS) as pool:
        per_photo = list(pool.map(one, range(len(photos)), photos))

    documents = [d for docs in per_photo for d in docs]
    return FindResult(
        documents=documents, tracks_raw=len(documents), dropped={}, segmenter_frames=len(photos),
        billed_frames=len(photos), masks_decoded=sum(1 for d in documents if d.methods != ["whole_photo"]),
        timings={"find_s": round(time.perf_counter() - start, 3), "segment_s": round(sum(seg_seconds), 3)},
    )
