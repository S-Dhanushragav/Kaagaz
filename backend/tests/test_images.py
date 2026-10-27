import cv2
import numpy as np
import pytest

from vision.images import encode_for_llm, read_image


def _decode(jpeg: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_UNCHANGED)


def test_landscape_downscaled_to_1024_long_side() -> None:
    out = _decode(encode_for_llm(np.zeros((2000, 3000, 3), np.uint8)))
    assert out.shape[:2] == (683, 1024)


def test_portrait_downscaled_to_1024_long_side() -> None:
    out = _decode(encode_for_llm(np.zeros((4000, 1000, 3), np.uint8)))
    assert out.shape[:2] == (1024, 256)


def test_small_image_not_upscaled() -> None:
    out = _decode(encode_for_llm(np.zeros((300, 500, 3), np.uint8)))
    assert out.shape[:2] == (300, 500)


def test_output_is_jpeg() -> None:
    assert encode_for_llm(np.zeros((10, 10, 3), np.uint8))[:2] == b"\xff\xd8"


def test_bgra_and_grayscale_accepted() -> None:
    assert _decode(encode_for_llm(np.zeros((50, 50, 4), np.uint8))) is not None
    assert _decode(encode_for_llm(np.zeros((50, 50), np.uint8))) is not None


def test_empty_image_rejected() -> None:
    with pytest.raises(ValueError):
        encode_for_llm(np.zeros((0, 0, 3), np.uint8))


def test_read_image_non_ascii_path(tmp_path) -> None:
    path = tmp_path / "कागज़.png"
    ok, buf = cv2.imencode(".png", np.full((20, 30, 3), 255, np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())
    assert read_image(path).shape == (20, 30, 3)


def test_read_image_bad_file(tmp_path) -> None:
    path = tmp_path / "x.jpg"
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        read_image(path)
