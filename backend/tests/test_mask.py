"""Identity-number masking for thumbnails: box validation, blurring only the boxed area, unreadable previews,
and the vision locator's reply handling (no model calls)."""

import numpy as np
import pytest

from agents.id_locator import RESPONSE_FORMAT, locate_id_numbers
from clients.llm import LLMError, LLMResponse, TokenUsage
from vision.mask import blur_boxes, preview, valid_boxes


def _card() -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(0, 255, (600, 1000, 3), dtype=np.uint8)  # high-frequency "text" everywhere


def test_valid_boxes_clamps_orders_and_drops_bad_ones() -> None:
    raw = [{"x0": 0.6, "y0": 0.7, "x1": 0.2, "y1": 0.8},  # corners swapped
           {"x0": -0.1, "y0": 0.5, "x1": 0.5, "y1": 0.55},  # off the edge
           {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},  # the whole card: not a number
           {"x0": 0.1, "y0": 0.1, "x1": 0.105, "y1": 0.2},  # too thin
           {"x0": "a"}, None]
    assert valid_boxes(raw) == [(0.2, 0.7, 0.6, 0.8), (0.0, 0.5, 0.5, 0.55)]
    assert valid_boxes(None) == [] and valid_boxes({"x0": 1}) == []


def test_blur_changes_only_the_padded_box() -> None:
    img = _card()
    out = blur_boxes(img, [(0.3, 0.5, 0.7, 0.6)])
    box = (slice(300, 360), slice(300, 700))
    assert out[box].std() < img[box].std() / 4  # the digits' area is flattened
    assert np.array_equal(out[:200], img[:200]) and np.array_equal(out[:, :200], img[:, :200])  # elsewhere untouched
    assert np.array_equal(blur_boxes(img, []), img)


def test_preview_keeps_nothing_readable() -> None:
    img = _card()
    assert preview(img).shape == img.shape and preview(img).std() < img.std() / 4


def _reply(text: str):
    def llm(prompt, **kwargs):
        assert kwargs["task"] == "vision" and kwargs["response_format"] is RESPONSE_FORMAT and kwargs["redact"]
        return LLMResponse(text=text, usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                           cached=False, model="m", provider="p", task="vision")
    return llm


def test_locator_reads_boxes_and_reports_failures() -> None:
    boxes = locate_id_numbers(b"jpg", llm=_reply('{"boxes": [{"x0": 0.2, "y0": 0.6, "x1": 0.7, "y1": 0.68}]}'))
    assert boxes == [(0.2, 0.6, 0.7, 0.68)]
    assert locate_id_numbers(b"jpg", llm=_reply('{"boxes": []}')) == []
    assert locate_id_numbers(b"jpg", llm=_reply("no json here")) is None

    def failing(prompt, **kwargs):
        raise LLMError("down")
    assert locate_id_numbers(b"jpg", llm=failing) is None


@pytest.mark.parametrize("schema_key", ["x0", "y0", "x1", "y1"])
def test_response_format_asks_for_coordinates_only(schema_key: str) -> None:
    item = RESPONSE_FORMAT["json_schema"]["schema"]["properties"]["boxes"]["items"]
    assert item["properties"][schema_key] == {"type": "number"} and set(item["properties"]) == {"x0", "y0", "x1", "y1"}
