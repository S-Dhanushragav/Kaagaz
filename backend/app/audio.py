"""A spoken question from the browser (MediaRecorder: WebM/Opus on Android Chrome, MP4/AAC on iPhone Safari) as the
WAV Muse Voice Transcribe takes: mono 16-bit PCM at 16 kHz, via ffmpeg.

The clip is written to a private temporary file only for ffmpeg (MP4 from Safari may keep its index at the end, so
it cannot be read from a pipe) and deleted at once; nothing of the audio is kept. Silence is detected here so an
empty recording never reaches the API.
"""

import array
import io
import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

RATE = 16000
MIN_SECONDS = 0.4
SILENCE_DBFS = -50.0  # a whole clip quieter than this (RMS) is silence


class AudioError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code  # unreadable | silent | too_long


def to_wav16k(data: bytes, max_s: float) -> tuple[bytes, float]:
    """(WAV bytes, seconds). Raises AudioError for a clip ffmpeg cannot read, a silent or empty one, or one longer than
    `max_s` (+1 s of slack for the stop tap)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is needed for spoken questions")
    if not data:
        raise AudioError("silent", "the recording is empty")
    with tempfile.TemporaryDirectory(prefix="kaagaz-q-") as folder:
        src = Path(folder) / "clip"
        src.write_bytes(data)
        done = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(src), "-t", str(max_s + 1), "-vn", "-ac", "1",
                               "-ar", str(RATE), "-sample_fmt", "s16", "-f", "wav", "pipe:1"],
                              capture_output=True, timeout=30)
    if done.returncode != 0 or len(done.stdout) <= 44:
        raise AudioError("unreadable", "the recording could not be read")
    wav = _fix_header(done.stdout)
    seconds, level = measure(wav)
    if seconds > max_s + 1.5:
        raise AudioError("too_long", "the recording is too long")
    if seconds < MIN_SECONDS or level < SILENCE_DBFS:
        raise AudioError("silent", "nothing was heard")
    return wav, seconds


def _fix_header(wav: bytes) -> bytes:
    """ffmpeg writing to a pipe cannot go back to fill in the sizes: rewrite the WAV with a proper header."""
    i = wav.find(b"data")
    if i < 0:
        raise AudioError("unreadable", "the recording could not be read")
    pcm = wav[i + 8:]
    pcm = pcm[: len(pcm) - len(pcm) % 2]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()


def measure(wav: bytes) -> tuple[float, float]:
    """(seconds, RMS level in dBFS) of a mono 16-bit WAV."""
    with wave.open(io.BytesIO(wav), "rb") as w:
        frames, rate = w.readframes(w.getnframes()), w.getframerate()
    samples = array.array("h", frames)
    if not samples:
        return 0.0, -120.0
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return len(samples) / rate, 20 * math.log10(rms / 32768) if rms > 0 else -120.0
