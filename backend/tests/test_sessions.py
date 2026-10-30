"""Sessions on the fake graph: sample run, pause at the question, answers (buttons and spoken), progress,
upload checks (length), rate limit, cleanup after the time limit."""

import time
from pathlib import Path

import pytest

import app.sessions as sessions_module
from agents.answers import AnswerResult, Match
from app.config import get_settings
from app.sessions import SessionError, SessionManager
from graph.build import build_graph
from tests.test_graph import _deps


@pytest.fixture
def manager(monkeypatch, tmp_path) -> SessionManager:
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"video")
    s = get_settings()
    monkeypatch.setattr(s, "sample_video", str(sample))  # absolute: REPO_ROOT / abs == abs
    monkeypatch.setattr(s, "sessions_dir", tmp_path / "sessions")
    monkeypatch.setattr(s, "max_sessions_per_hour", 2)
    return SessionManager(graph=build_graph(_deps([])))


def _wait(manager: SessionManager, session_id: str, timeout: float = 15.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        view = manager.view(session_id)
        if view["status"] != "running":
            return view
        time.sleep(0.05)
    raise AssertionError("session did not settle")


def test_sample_session_pauses_resumes_and_reports_progress(manager: SessionManager) -> None:
    session = manager.start_sample("en")
    view = _wait(manager, session.id)
    assert view["status"] == "waiting" and view["sample"]
    assert [s["done"] for s in view["stages"]] == [True, True, True, True, False, False]
    q = view["question"]
    assert q["question_id"] == "i1:which_is_correct" and view["household"] and view["results"]
    assert Path(get_settings().sample_video).exists()  # the sample is never deleted
    assert manager.speech_text(session.id, "question") == q["speech"]
    with pytest.raises(SessionError) as e:
        manager.answer_option(session.id, "i9:compare", 0)
    assert e.value.status == 409
    with pytest.raises(SessionError):
        manager.answer_option(session.id, q["question_id"], 7)
    sunil = next(i for i, o in enumerate(q["options"]) if "Sunil Ramesh Patil" in o)
    manager.answer_option(session.id, q["question_id"], sunil)
    done = _wait(manager, session.id)
    assert done["status"] == "done" and done["question"] is None
    assert all(s["done"] for s in done["stages"]) and done["plan"]["steps"] and done["speech"]
    assert manager.speech_text(session.id, "step-1") == done["speech"][1]["speech"]
    with pytest.raises(SessionError):
        manager.answer_option(session.id, q["question_id"], sunil)  # already answered


def test_spoken_answers_ask_again_then_buttons_and_only_a_match_resumes(manager, monkeypatch) -> None:
    session = manager.start_sample("hi")
    q = _wait(manager, session.id)["question"]
    replies = iter([
        AnswerResult(action="ask_again", say="again", attempts=[Match(option=None, heard="लूसा", reason="no number")]),
        AnswerResult(action="show_buttons", say="buttons", attempts=[Match(option=None, heard="लूसा", reason="no number"),
                                                                    Match(option=None, heard="हम्म", reason="no number")]),
    ])
    seen = []
    monkeypatch.setattr(sessions_module, "answer_from_audio",
                        lambda audio, prompt, language, earlier: seen.append(list(earlier)) or next(replies))
    assert manager.answer_audio(session.id, q["question_id"], b"wav")["action"] == "ask_again"
    assert manager.answer_audio(session.id, q["question_id"], b"wav")["action"] == "show_buttons"
    assert seen == [[], ["लूसा"]]  # the second try knows the first
    assert manager.view(session.id)["status"] == "waiting"  # no match: still waiting for buttons
    monkeypatch.setattr(sessions_module, "answer_from_audio", lambda audio, prompt, language, earlier: AnswerResult(
        action="answered", option=next(i for i, o in enumerate(q["options"]) if "Sunil Ramesh Patil" in o),
        attempts=[Match(option=1, heard="नंबर दो", reason="number")]))
    assert manager.answer_audio(session.id, q["question_id"], b"wav")["action"] == "answered"
    assert _wait(manager, session.id)["status"] == "done"


def test_upload_too_long_is_rejected_and_deleted(manager, monkeypatch) -> None:
    import vision.frames as frames

    folder = manager.new_upload_folder()
    upload = folder / "upload.bin"
    upload.write_bytes(b"x")
    monkeypatch.setattr(frames, "normalize_upload", lambda src, dst, max_s, long_side=1920: (dst.write_bytes(b"v"), 60.0)[1])
    with pytest.raises(SessionError) as e:
        manager.start_upload(upload, "mr")
    assert e.value.status == 413 and not folder.exists()


def test_upload_runs_and_the_video_is_deleted_after_finding(manager, monkeypatch) -> None:
    import vision.frames as frames

    folder = manager.new_upload_folder()
    upload = folder / "upload.bin"
    upload.write_bytes(b"x")
    monkeypatch.setattr(frames, "normalize_upload", lambda src, dst, max_s, long_side=1920: (dst.write_bytes(b"v"), 20.0)[1])
    session = manager.start_upload(upload, "mr")
    assert _wait(manager, session.id)["status"] == "waiting"
    assert not (folder / "upload.bin").exists() and not (folder / "video.mp4").exists()


def test_rate_limit_counts_uploads_per_hour(manager) -> None:
    manager.check_rate()
    manager.check_rate()
    with pytest.raises(SessionError) as e:
        manager.check_rate()
    assert e.value.status == 429
    manager.uploads = [time.time() - 3601] * 2  # an hour later
    manager.check_rate()


def test_everything_is_deleted_after_the_time_limit(manager) -> None:
    session = manager.start_sample("en")
    _wait(manager, session.id)
    folder = manager.folder(session.id)
    assert folder.exists()
    assert manager.cleanup(now=time.time() + 10) == []
    assert manager.cleanup(now=time.time() + get_settings().session_ttl_s + 1) == [session.id]
    assert not folder.exists() and session.id not in manager.sessions
    assert not manager.graph.get_state(session.config).values  # checkpoint gone
    with pytest.raises(SessionError) as e:
        manager.view(session.id)
    assert e.value.status == 404


def test_found_documents_are_listed_with_type_and_name_once_read(manager) -> None:
    session = manager.start_sample("en")
    view = _wait(manager, session.id)
    docs = {d["id"]: d for d in view["documents"]}
    assert list(docs) == ["rc", "id1"]  # in the order the finder handed them over
    assert docs["rc"]["doc_type"] == "ration_card" and docs["id1"]["doc_type"] == "identity_card"
    assert docs["id1"]["read"] and docs["id1"]["name_en"] == "Suneel Ramesh Patil"


def test_live_documents_before_reading_is_done() -> None:
    from app.sessions import live_documents

    reads = {"d1": {"document_id": "d1", "doc_type": "identity_card", "fields": {"name_en": "Savita", "name_mr": None}},
             "rc": {"document_id": "rc", "doc_type": "ration_card", "fields": {"head_name_mr": "आदित्य", "members": []}}}
    out = live_documents(["d1", "d2", "rc"], [], reads)
    assert out[0] == {"id": "d1", "doc_type": "identity_card", "name_en": "Savita", "name_mr": None, "read": True}
    assert out[1] == {"id": "d2", "doc_type": None, "name_en": None, "name_mr": None, "read": False}
    assert out[2]["name_mr"] == "आदित्य"  # a ration card is labelled with its head of family


def _jpeg(h: int = 1200, w: int = 900) -> bytes:
    import cv2
    import numpy as np

    yy, xx = np.mgrid[:h, :w]
    board = (((yy // 40) + (xx // 40)) % 2 * 255).astype(np.uint8)  # sharp detail that survives the thumbnail size
    return cv2.imencode(".jpg", np.dstack([board] * 3))[1].tobytes()


def _decode(data: bytes):
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


def test_identity_card_thumbnails_are_masked_once_and_go_with_the_session(manager) -> None:
    from graph.runtime import runtime

    calls = []
    manager.locator = lambda image: calls.append(image) or [(0.2, 0.6, 0.8, 0.7)]
    session = manager.start_sample("en")
    _wait(manager, session.id)
    crop = _jpeg()
    runtime(session.id).add_document("id1", [crop])  # id1 is read as an identity card
    masked = _decode(manager.thumbnail(session.id, "id1"))
    assert max(masked.shape[:2]) == 480 and calls == [crop]
    plain = _decode(manager.thumbnail(session.id, "id1"))
    assert calls == [crop]  # made once, then cached
    band, above = masked[300:330, 100:260], masked[:150]  # the number's band (480 px tall thumbnail)
    original = _decode(crop)
    assert band.std() < 20 < above.std()  # blurred band, everything else still detailed
    assert plain.shape == masked.shape and original is not None
    manager.delete(session.id)
    with pytest.raises(SessionError) as e:
        manager.thumbnail(session.id, "id1")
    assert e.value.status == 404


def test_identity_card_without_a_box_is_never_shown(manager) -> None:
    from graph.runtime import runtime

    session = manager.start_sample("en")
    _wait(manager, session.id)
    runtime(session.id).add_document("id1", [_jpeg()])
    manager.locator = lambda image: []  # the model saw no number
    with pytest.raises(SessionError) as e:
        manager.thumbnail(session.id, "id1")
    assert e.value.status == 404
    manager.locator = lambda image: (_ for _ in ()).throw(AssertionError("asked again"))
    with pytest.raises(SessionError):
        manager.thumbnail(session.id, "id1")  # cached: shown as an icon, not asked again
    runtime(session.id).add_document("id1", [_jpeg()])  # a close-up replaces the crop: located again
    manager.locator = lambda image: None  # the call failed: icon now, not cached
    with pytest.raises(SessionError):
        manager.thumbnail(session.id, "id1")
    assert "id1" not in runtime(session.id).thumbs


def test_unread_documents_get_an_unreadable_preview_and_others_their_crop(manager) -> None:
    from graph.runtime import runtime

    manager.locator = lambda image: (_ for _ in ()).throw(AssertionError("not an identity card"))
    session = manager.start_sample("en")
    _wait(manager, session.id)
    rt = runtime(session.id)
    rt.add_document("rc", [_jpeg()])
    rt.add_document("new", [_jpeg()])  # handed over by the finder, not read yet
    card = _decode(manager.thumbnail(session.id, "rc"))
    unread = _decode(manager.thumbnail(session.id, "new"))
    assert card.std() > 40 and unread.std() < 20  # the ration card as it is; the unread one only as blocks
    with pytest.raises(SessionError):
        manager.thumbnail(session.id, "nope")
