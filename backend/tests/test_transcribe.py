"""Transcribe client: request format, WAV checks, cache. The HTTP call is faked."""

import json

import numpy as np
import pytest

import clients.transcribe as tr
from app.config import get_settings
from clients.tts import wav_bytes

WAV = wav_bytes(np.zeros(16000, dtype=np.float32), 16000)
fake_api_settings: list = []


@pytest.fixture
def fake_api(monkeypatch, tmp_path):
    sent = []
    fake_api_settings.clear()

    def post(url, body, content_type, api_key, **settings):
        sent.append((url, body, content_type))
        fake_api_settings.append(settings)
        return {"sessionId": "s1", "transcript": " दुसरे ", "audioDurationMs": 1000, "turns": []}

    s = get_settings()
    monkeypatch.setattr(tr, "_post", post)
    monkeypatch.setattr(s, "cache_dir", tmp_path)
    monkeypatch.setattr(s, "meta_transcribe_model", "muse-voice-transcribe-1.0")
    monkeypatch.setattr(s, "meta_base_url", "https://api.meta.ai/v1")
    return sent


def test_request_has_model_language_bias_and_keywords_and_is_cached(fake_api) -> None:
    result = tr.transcribe(WAV, "mr", keywords=["पहिले", "दुसरे", "पहिले"])
    assert result.text == "दुसरे" and result.audio_ms == 1000 and not result.cached
    url, body, content_type = fake_api[0]
    assert url == "https://api.meta.ai/v1/asr/transcribe" and content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=")[1].encode()
    parts = body.split(b"--" + boundary)
    request_part = next(p for p in parts if b'name="request"' in p)
    request = json.loads(request_part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0])
    assert request == {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK",
                       "languageBias": ["Marathi"], "keywords": ["पहिले", "दुसरे"]}
    assert any(b'name="audio"; filename="audio.wav"' in p and WAV in p for p in parts)
    again = tr.transcribe(WAV, "mr", keywords=["पहिले", "दुसरे"])
    assert again.cached and len(fake_api) == 1
    tr.transcribe(WAV, "hi")  # different settings: a new call
    assert len(fake_api) == 2


@pytest.mark.parametrize("rate, channels", [(8000, 1), (44100, 1), (16000, 2)])
def test_wrong_audio_format_is_rejected_before_sending(fake_api, rate: int, channels: int) -> None:
    samples = np.zeros(rate * channels, dtype=np.float32)
    data = wav_bytes(samples, rate)
    if channels == 2:  # rewrite the header as stereo
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"\x00\x00" * rate * 2)
        data = buf.getvalue()
    with pytest.raises(tr.TranscribeError, match="mono 16-bit PCM"):
        tr.transcribe(data, "hi")
    with pytest.raises(tr.TranscribeError, match="not a WAV"):
        tr.transcribe(b"not audio", "hi")
    assert not fake_api


def test_interactive_timeout_is_10_s_with_one_retry_then_an_error(monkeypatch, tmp_path) -> None:
    calls = []

    def urlopen(req, timeout):
        calls.append(timeout)
        raise TimeoutError("timed out")

    s = get_settings()
    monkeypatch.setattr(s, "cache_dir", tmp_path)
    monkeypatch.setattr(s, "meta_transcribe_model", "muse-voice-transcribe-1.0")
    monkeypatch.setattr(s, "meta_base_url", "https://api.meta.ai/v1")
    monkeypatch.setattr(tr.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(tr.time, "sleep", lambda s: None)
    with pytest.raises(tr.TranscribeError, match="timed out"):
        tr.transcribe(WAV, "hi")
    assert calls == [10.0, 10.0]  # one try, one retry
    calls.clear()
    with pytest.raises(tr.TranscribeError):
        tr.transcribe(WAV, "hi", **tr.EVAL_SETTINGS)
    assert calls == [120.0] * 4  # evals: patient


def test_settings_reach_the_http_call(fake_api) -> None:
    tr.transcribe(WAV, "en", **tr.EVAL_SETTINGS)
    assert fake_api_settings[-1] == tr.EVAL_SETTINGS
