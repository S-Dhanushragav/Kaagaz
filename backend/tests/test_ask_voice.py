"""Spoken questions: browser clips (WebM/Opus, MP4/AAC) converted with ffmpeg to 16 kHz mono WAV, silence and broken
clips refused, POST /ask/transcribe (counts as a question, a one-use ticket for the ask that follows, the transcript
never cached or logged), and speech-input languages set by configuration only."""

import io
import logging
import math
import shutil
import struct
import subprocess
import wave

import pytest
from fastapi.testclient import TestClient

from app.audio import AudioError, measure, to_wav16k
from clients.transcribe import Transcript, TranscribeError

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _wav(seconds: float, amplitude: float = 0.3, rate: int = 48000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(amplitude * 32767 * math.sin(2 * math.pi * 440 * i / rate)))
                               for i in range(int(seconds * rate))))
    return out.getvalue()


def _encode(wav: bytes, fmt: str, tmp_path=None) -> bytes:
    """What a browser sends: WebM/Opus (Android Chrome) or an MP4/AAC file with its index at the end (iPhone Safari)."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.wav", Path(d) / f"out.{fmt}"
        src.write_bytes(wav)
        codec = ["-c:a", "libopus"] if fmt == "webm" else ["-c:a", "aac"]  # mp4: no faststart, moov at the end
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(src), *codec, str(dst)], check=True)
        return dst.read_bytes()


@needs_ffmpeg
@pytest.mark.parametrize("fmt", ["webm", "mp4"])
def test_browser_clips_become_16k_mono_wav(fmt) -> None:
    wav, seconds = to_wav16k(_encode(_wav(2.0), fmt), max_s=30)
    with wave.open(io.BytesIO(wav), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
    assert 1.8 < seconds < 2.3 and measure(wav)[1] > -30


@needs_ffmpeg
def test_silent_empty_broken_and_long_clips_are_refused() -> None:
    for data, code in ((_encode(_wav(2.0, amplitude=0.0), "webm"), "silent"), (b"", "silent"),
                       (b"not audio at all", "unreadable"), (_encode(_wav(0.2), "webm"), "silent")):
        with pytest.raises(AudioError) as e:
            to_wav16k(data, max_s=30)
        assert e.value.code == code
    wav, seconds = to_wav16k(_encode(_wav(5.0), "webm"), max_s=2)  # cut at the limit + 1 s
    assert seconds <= 3.1


def test_speech_languages_come_from_configuration(monkeypatch) -> None:
    from app.config import get_settings
    from clients.transcribe import transcribe

    s = get_settings()
    assert s.asr_language_names == {"en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu",
                                    "kn": "Kannada"}
    monkeypatch.setattr(s, "asr_languages", "en:English,hi:Hindi")
    assert s.asr_language_names == {"en": "English", "hi": "Hindi"}  # a language is added or removed here only
    monkeypatch.setattr(s, "meta_transcribe_model", "m")
    monkeypatch.setattr(s, "meta_base_url", "https://example.invalid")
    with pytest.raises(TranscribeError, match="ASR_LANGUAGES"):
        transcribe(_wav(0.5, rate=16000), "xx")


# ---------- the endpoint ----------

@pytest.fixture
def api(monkeypatch):
    from app.api.ask import AskService
    from app.main import app
    from app.sessions import SessionError
    from storage.store import MemoryStore

    class NoSessions:
        def get(self, session_id):
            raise SessionError(404, "No such session.")

    calls = []

    def fake_transcribe(audio, language=None, keywords=None, **kw):
        calls.append({"language": language, "keywords": keywords, **kw})
        return Transcript(text="लाडकी बहीण योजनेसाठी वयाची अट काय आहे?", audio_ms=2000, request_s=0.5)

    monkeypatch.setattr("clients.transcribe.transcribe", fake_transcribe)
    monkeypatch.setattr("app.audio.to_wav16k", lambda data, max_s: (_wav(1.0, rate=16000), 1.0))
    monkeypatch.setattr("agents.ask.ask", lambda *a, **k: __import__("agents.ask", fromlist=["AskAnswer"]).AskAnswer(
        kind="answer", text="ok"))
    for name, value in (("ask", AskService()), ("store", MemoryStore()), ("sessions", NoSessions())):
        monkeypatch.setattr(app.state, name, value, raising=False)
    return TestClient(app), calls


def _post(client, language="mr", **headers):
    return client.post("/ask/transcribe", data={"language": language},
                       files={"audio": ("q.webm", b"webm-bytes", "audio/webm")}, headers=headers)


def test_transcribe_puts_text_in_the_box_and_keeps_nothing(api, caplog) -> None:
    client, calls = api
    with caplog.at_level(logging.INFO):
        body = _post(client).json()
    assert body["text"].startswith("लाडकी") and body["voice_ticket"] and set(body["timings"]) == {"audio_s", "convert_s",
                                                                                                    "transcribe_s"}
    assert calls == [{"language": "mr", "keywords": None, "cache": False}]  # no keyword biasing for mr; not cached
    assert "लाडकी" not in caplog.text  # the transcript is never logged


def test_a_spoken_question_counts_once(api, monkeypatch) -> None:
    from app.config import get_settings

    client, _ = api
    monkeypatch.setattr(get_settings(), "ask_per_ip_hour", 2)
    ticket = _post(client).json()["voice_ticket"]
    ask = lambda t=None: client.post("/ask", json={"question": "q", "language": "mr", "voice_ticket": t})  # noqa: E731
    assert ask(ticket).status_code == 200  # counted when transcribed, not again
    assert ask(ticket).status_code == 200  # a used ticket counts: the second (and last) question this hour
    assert ask(ticket).status_code == 429 and _post(client).status_code == 429


def test_transcribe_errors_are_friendly(api, monkeypatch) -> None:
    from app.audio import AudioError

    client, _ = api
    assert _post(client, language="bn").json()["detail"]["code"] == "language"  # not in ASR_LANGUAGES

    def silent(data, max_s):
        raise AudioError("silent", "nothing was heard")

    monkeypatch.setattr("app.audio.to_wav16k", silent)
    r = _post(client)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "silent"
    monkeypatch.setattr("app.audio.to_wav16k", lambda data, max_s: (_wav(1.0, rate=16000), 1.0))

    def down(*a, **k):
        raise TranscribeError("HTTP 503")

    monkeypatch.setattr("clients.transcribe.transcribe", down)
    r = _post(client)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "unavailable"
    monkeypatch.setattr("clients.transcribe.transcribe", lambda *a, **k: Transcript(text=" ", audio_ms=0, request_s=0))
    assert _post(client).json()["detail"]["code"] == "silent"
