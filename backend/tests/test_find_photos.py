"""Photo finder offline: a fake segmenter outlines the documents; crops come out upright, two different images per
document (two independent reads), tiny and repeated detections dropped, a photo with nothing found read whole."""

from pathlib import Path

import cv2
import numpy as np

from clients.segmenter import SegmentResult, Track, TrackFrame
from graph.nodes.find_photos import find_in_photos
from tests.test_orient import DOCS, place
from vision.orient import rotate_quarters


class MaskSegmenter:
    """Finds non-grey regions (the documents placed on a grey canvas) in the photo it is sent."""

    def __init__(self, extra_boxes: list[tuple[float, float, float, float]] = ()) -> None:
        self.calls, self.extra = 0, list(extra_boxes)

    def segment_image(self, jpeg: bytes, size: tuple[int, int], prompt: str = "document") -> SegmentResult:
        self.calls += 1
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert (image.shape[1], image.shape[0]) == size
        found = (np.abs(image.astype(int) - 90).max(axis=2) > 25).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(found)
        tracks = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < 50:
                continue
            mask = labels == i
            tracks.append(Track(f"document:{i}", prompt, {0: TrackFrame(0, (x, y, x + w, y + h), 0.9, lambda m=mask: m)}))
        for j, box in enumerate(self.extra):  # a tiny detection: should be ignored
            m = np.zeros(image.shape[:2], bool)
            m[int(box[1]):int(box[3]), int(box[0]):int(box[2])] = True
            tracks.append(Track(f"document:x{j}", prompt, {0: TrackFrame(0, box, 0.5, lambda m=m: m)}))
        return SegmentResult(tracks=tracks, frame_size=size, billed_frames=1)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Coarse picture match (64 px): the photo is segmented at a smaller size, so corners are a few pixels off."""
    a = cv2.resize(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), (64, 64), interpolation=cv2.INTER_AREA).astype(float)
    b = cv2.resize(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), (64, 64), interpolation=cv2.INTER_AREA).astype(float)
    a, b = (a - a.mean()) / (a.std() + 1e-6), (b - b.mean()) / (b.std() + 1e-6)
    return float((a * b).mean())


def _save(path: Path, image: np.ndarray) -> Path:
    cv2.imwrite(str(path), image)
    return path


def test_documents_in_photos_come_out_upright_with_two_reads_each(tmp_path: Path) -> None:
    portrait, card = cv2.imread(str(DOCS["portrait"])), cv2.imread(str(DOCS["landscape"]))
    tilted, _ = place(portrait, 30)
    sideways, _ = place(card, 90)
    two = np.full((1800, 2600, 3), 90, np.uint8)  # two documents in one photo
    two[100:100 + card.shape[0], 100:100 + card.shape[1]] = card
    two[100:100 + portrait.shape[0], 1400:1400 + portrait.shape[1]] = portrait
    photos = [_save(tmp_path / "a.jpg", tilted), _save(tmp_path / "b.jpg", sideways), _save(tmp_path / "c.jpg", two)]
    handed = []
    seg = MaskSegmenter(extra_boxes=[(0, 0, 10, 10)])
    result = find_in_photos(photos, segmenter=seg, on_document=handed.append)
    assert seg.calls == 3 and sorted(d.document.id for d in handed) == [d.document.id for d in result.documents]
    assert [d.document.id for d in result.documents] == ["doc01a", "doc02a", "doc03a", "doc03b"]
    expected = [portrait, card, card, portrait]
    for d, original in zip(sorted(result.documents, key=lambda d: d.document.id), expected):
        first, second = d.document.images
        assert first != second  # two different images: two separate reads
        crop = cv2.imdecode(np.frombuffer(first, np.uint8), cv2.IMREAD_COLOR)
        scores = [similarity(rotate_quarters(crop, k), original) for k in range(4)]
        assert int(np.argmax(scores)) == 0 and scores[0] > 0.8, (d.document.id, np.round(scores, 2))


def test_a_photo_with_nothing_found_is_read_whole(tmp_path: Path) -> None:
    blank = _save(tmp_path / "blank.jpg", np.full((600, 800, 3), 90, np.uint8))
    result = find_in_photos([blank], segmenter=MaskSegmenter())
    assert len(result.documents) == 1 and result.documents[0].methods == ["whole_photo"]
