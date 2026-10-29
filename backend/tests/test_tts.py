"""TTS client: WAV format, cache by (model, text), clear errors. The model itself is faked (no torch needed)."""

import wave

import numpy as np
import pytest

import clients.tts as tts
from app.config import get_settings


@pytest.fixture
def fake_tts(monkeypatch, tmp_path):
    calls = []

    def synth(model: str, text: str):
        calls.append((model, text))
        return np.sin(np.linspace(0, 100, 16000)).astype(np.float32) * 0.5, 16000

    monkeypatch.setattr(tts, "_synthesize", synth)
    monkeypatch.setattr(get_settings(), "cache_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "tts_model_mr", "facebook/mms-tts-mar")
    return calls


def test_wav_is_16_bit_mono_and_cached_by_model_and_text(fake_tts) -> None:
    first = tts.synthesize("पहिले", "mr")
    with wave.open(str(first.path), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 16000)
    assert not first.cached and first.seconds == 1.0
    again = tts.synthesize("पहिले", "mr")
    assert again.cached and again.path == first.path and again.synth_s == 0.0
    tts.synthesize("दुसरे", "mr")
    assert fake_tts == [("facebook/mms-tts-mar", "पहिले"), ("facebook/mms-tts-mar", "दुसरे")]


def test_missing_model_setting_is_a_clear_error(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "tts_model_hi", "")
    with pytest.raises(tts.TTSError, match="TTS_MODEL_HI"):
        tts.synthesize("नमस्ते", "hi")


def test_wav_bytes_clips_to_int16() -> None:
    data = tts.wav_bytes(np.array([2.0, -2.0, 0.0], dtype=np.float32), 16000)
    assert data[:4] == b"RIFF" and data[-6:] == np.array([32767, -32767, 0], dtype="<i2").tobytes()
