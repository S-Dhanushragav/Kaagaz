"""SAM 3.1 output parsing on a 2-frame fixture from the probe call (synthetic video, no network)."""

import re
from pathlib import Path

import numpy as np
import pytest

from clients.segmenter import Sam3ModalSegmenter, parse_sam_output, parse_sam_output_official

FIXTURE = Path(__file__).parent / "fixtures" / "sam31_video_output.txt"
SIZE = (720, 1280)


@pytest.fixture(scope="module")
def tracks():
    return parse_sam_output(FIXTURE.read_text(encoding="utf-8"), "document", SIZE)


def test_one_track_per_object_with_prompt_in_id(tracks) -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    ids = {m for m in re.findall(r"(?:^<\d+f>|,)(\d+)<\|box", text, flags=re.M)}
    assert {t.track_id for t in tracks} == {f"document:{i}" for i in ids}
    assert all(t.prompt == "document" for t in tracks)


def test_boxes_are_half_open_and_match_the_wire(tracks) -> None:
    first = FIXTURE.read_text(encoding="utf-8").splitlines()[0]
    m = re.match(r"<0f>(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);", first)
    obj, x1, y1, x2, y2 = (int(v) for v in m.groups())
    t = next(t for t in tracks if t.track_id == f"document:{obj}")
    assert t.frames[0].box == (x1, y1, x2 + 1, y2 + 1)  # inclusive wire x2/y2 -> half-open
    assert 0 < t.frames[0].score <= 1


def test_masks_decode_to_full_frame_inside_their_box(tracks) -> None:
    for t in tracks:
        for f in t.frames.values():
            mask = f.mask()
            assert mask.shape == (SIZE[1], SIZE[0]) and mask.dtype == bool
            x1, y1, x2, y2 = (int(v) for v in f.box)
            inside = mask[y1:y2, x1:x2].sum()
            assert inside == mask.sum() > 0
            assert inside / ((x2 - x1) * (y2 - y1)) > 0.5  # documents fill most of their box


def test_frames_are_zero_based_indices(tracks) -> None:
    assert {f for t in tracks for f in t.frames} <= {0, 1}


def test_matches_official_parser(tracks) -> None:
    """Our lazy token reader returns exactly what Meta's parser returns: boxes and mask payloads."""
    official = parse_sam_output_official(FIXTURE.read_text(encoding="utf-8"))
    ours = {(f.frame, t.track_id.split(":")[1]): f for t in tracks for f in t.frames.values()}
    assert len(official) == len(ours) > 0
    for frame, obj, box, mask in official:
        f = ours[(frame, obj)]
        assert f.box == box
        spec = f.mask_spec
        assert (spec.encoding, spec.payload, spec.width, spec.height) == (mask.encoding, mask.payload, mask.width, mask.height)


def test_empty_output_is_no_tracks() -> None:
    assert parse_sam_output("", "document", SIZE) == []


def test_modal_backend_is_a_stub(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError):
        Sam3ModalSegmenter().segment_video(tmp_path / "v.mp4", ["document"])
