"""Spoken answers: matched by number words or not-sure words only; never by names; retry once, then buttons."""

import pytest

import agents.answers as answers
from agents.answers import NOT_SURE, _normalize, keywords, match_answer, question_prompt, resolve, use_keywords
from agents.voice import LANGUAGES, load_voice
from clients.transcribe import TranscribeError, Transcript
from schemas.fixes import PlannerIssue

NAMES = ["Sunil Ramesh Patil", "Suneel Ramesh Patil", NOT_SURE]
NAMES_MR = ["सुनील रमेश पाटील", "सुनिल रमेश पाटील", NOT_SURE]


@pytest.mark.parametrize("language, heard, option", [
    ("en", "Second.", 1), ("en", "the first one", 0), ("en", "The second one,", 1), ("en", "number one", 0), ("en", "Two", 1), ("en", "2", 1), ("en", "option 1", 0),
    ("en", "Third", 2), ("en", "I'm not sure", 2), ("en", "I don't know.", 2), ("en", "2nd", 1),
    ("hi", "दूसरा", 1), ("hi", "पहला वाला", 0), ("hi", "दूसरे वाला सही है।", 1), ("hi", "नंबर दो", 1), ("hi", "दो", 1),
    ("hi", "२", 1), ("hi", "पता नहीं", 2), ("hi", "मुझे नहीं पता", 2), ("hi", "तीसरा", 2),
    ("mr", "दुसरे", 1), ("mr", "पहिलं", None), ("mr", "पहिला", 0), ("mr", "दुसरं नाव बरोबर आहे", None),
    ("mr", "दुसरा", 1), ("mr", "दोन", 1), ("mr", "१", 0), ("mr", "माहीत नाही", 2), ("mr", "मला माहिती नाही.", 2),
])
def test_number_and_not_sure_words(language: str, heard: str, option: int | None) -> None:
    assert match_answer(heard, NAMES, language).option == option


@pytest.mark.parametrize("language, heard", [
    ("en", "Sunil Ramesh Patil"), ("en", "Suneel"), ("en", "the one on the ration card"),
    ("hi", "सुनील रमेश पाटील"), ("mr", "सुनिल रमेश पाटील"), ("mr", "रेशन कार्डवरचे"), ("en", ""),
])
def test_names_and_anything_else_never_match(language: str, heard: str) -> None:
    options = NAMES_MR if language != "en" else NAMES
    assert match_answer(heard, options, language).option is None


@pytest.mark.parametrize("heard, reason", [
    ("first or second", "several numbers"), ("second, not sure", "several numbers"), ("the fifth", "out of range"),
    ("hello", "no number"),
])
def test_ambiguous_or_out_of_range_is_no_match(heard: str, reason: str) -> None:
    m = match_answer(heard, NAMES, "en")
    assert m.option is None and m.reason == reason


def test_compare_options_and_numbers_beyond_three() -> None:
    options = ["same", "different", NOT_SURE]
    assert match_answer("first", options, "en").option == 0
    assert match_answer("same", options, "en").option is None  # the option's own word is not an answer
    four = ["a", "b", "c", NOT_SURE]
    assert match_answer("fourth", four, "en").option == 3 and match_answer("not sure", four, "en").option == 3


def test_ask_again_once_then_buttons() -> None:
    first_miss = resolve(["Sunil"], NAMES, "en")
    assert first_miss.action == "ask_again" and first_miss.say == load_voice("en").answers.retry
    assert resolve(["Sunil", "second"], NAMES, "en").option == 1
    two_misses = resolve(["Sunil", "the name on the ration card"], NAMES, "en")
    assert two_misses.action == "show_buttons" and two_misses.option is None
    assert two_misses.say == load_voice("en").answers.buttons
    assert resolve(["Sunil", "hmm", "second"], NAMES, "en").action == "show_buttons"  # never a third try
    assert resolve(["दुसरे"], NAMES_MR, "mr").action == "answered"


NAME_ISSUE = PlannerIssue(id="i1", type="name_mismatch", severity="blocker", member_id="r1",
                          member_name="Sunil Ramesh Patil", member_name_mr="सुनील रमेश पाटील",
                          documents={"rc": "ration_card", "id_m1": "identity_card"},
                          values={"rc": "सुनील रमेश पाटील / Sunil Ramesh Patil", "id_m1": "सुनिल रमेश पाटील / Suneel Ramesh Patil"},
                          detail="")
LATIN_ONLY = NAME_ISSUE.model_copy(update={"values": {"rc": "Gauri Hrishikesh Waghmare", "id_m1": "Gauri Hrishikesh Vaghmare"}})
DOB_ISSUE = NAME_ISSUE.model_copy(update={"type": "dob_mismatch", "documents": {"id_m1": "identity_card", "cc": "caste_certificate"},
                                          "values": {"id_m1": "05/02/1981", "cc": "04/02/1981"}})


@pytest.mark.parametrize("language", LANGUAGES)
def test_prompt_names_documents_and_numbered_options_carry_the_values(language: str) -> None:
    vocab = load_voice(language).answers
    prompt = question_prompt(NAME_ISSUE, "which_is_correct", language)
    script = "Sunil" if language == "en" else "सुनील"
    question = prompt.speech.split(vocab.labels[0])[0]
    assert script not in question.split(":", 1)[1]  # after the member's name, the question names documents only
    assert load_voice(language).documents["ration_card"] in question
    assert all(f"{label}:" in prompt.speech for label in vocab.labels[:3]) and prompt.speech.endswith(vocab.instruction)
    assert prompt.options[-1] == NOT_SURE and len(prompt.shown) == 3
    assert all(s in prompt.screen for s in prompt.shown[:2])  # the screen shows both spellings
    assert "? " in prompt.speech or "?" in prompt.speech  # the question ends before the options start
    assert not any(c.isdigit() for c in prompt.speech)


@pytest.mark.parametrize("language", LANGUAGES)
def test_keywords_cover_the_number_words(language: str) -> None:
    vocab = load_voice(language).answers
    kw = keywords(NAMES, language)
    assert vocab.labels[0].lower() in [k.lower() for k in kw] and vocab.not_sure[0] in kw
    assert not any(k.isdigit() for k in kw)
    assert not any(name in kw for name in NAMES[:2])  # names are never keywords
    assert len(vocab.labels) == len(vocab.numbers) == 5
    for i, label in enumerate(vocab.labels):  # every label read aloud is itself a matching answer
        assert match_answer(label, ["a", "b", "c", "d", NOT_SURE], language).option == i


def test_spoken_prompt_spells_out_dates_and_has_full_stops() -> None:
    prompt = question_prompt(DOB_ISSUE, "which_is_correct", "en")
    assert "Number one: four February nineteen hundred eighty-one." in prompt.speech
    assert "05/02/1981" in prompt.screen and "1981" not in prompt.speech


@pytest.mark.parametrize("language, english_only", [("hi", True), ("mr", True), ("en", False)])
def test_latin_only_difference_points_hindi_and_marathi_to_the_screen(language: str, english_only: bool) -> None:
    prompt = question_prompt(LATIN_ONLY, "which_is_correct", language)
    assert prompt.english_only is english_only
    assert "Vaghmare" in prompt.screen and "Waghmare" in prompt.screen  # the screen shows both spellings
    if english_only:
        assert not any("a" <= c.lower() <= "z" for c in prompt.speech)  # no Latin text for a Devanagari voice
        assert load_voice(language).answers.english_only.split(":")[-1].strip()[:6] in prompt.speech
    assert not question_prompt(NAME_ISSUE, "which_is_correct", language).english_only
    assert not question_prompt(DOB_ISSUE, "which_is_correct", language).english_only  # dates can be said


@pytest.mark.parametrize("language, heard, option", [
    ("mr", "माहित नाही", 2), ("mr", "मला माहित नाहि.", 2), ("hi", "नबर दो", 1), ("mr", "नबर दोन", 1),
    ("hi", "दुसरा", 1), ("hi", "तिसरा", 2), ("mr", "पहीले", 0), ("hi", "पाँचवा", 4), ("hi", "पांचवाँ", 4),
])
def test_spelling_tolerant_matching(language: str, heard: str, option: int) -> None:
    options = ["a", "b", "c", "d", NOT_SURE] if option == 4 else NAMES
    assert match_answer(heard, options, language).option == option


@pytest.mark.parametrize("language", LANGUAGES)
def test_number_words_stay_distinct_after_spelling_folding(language: str) -> None:
    vocab = load_voice(language).answers
    seen: dict[str, int] = {}
    for i, words in enumerate(vocab.numbers):
        for w in words:
            assert seen.setdefault(_normalize(w), i) == i, (w, i)
    assert not set(seen) & {_normalize(w) for w in vocab.not_sure}


def test_keyword_biasing_is_english_only_by_default(monkeypatch) -> None:
    assert use_keywords("en") and not use_keywords("hi") and not use_keywords("mr")
    monkeypatch.setattr(answers.get_settings(), "asr_keyword_languages", "en,hi")
    assert use_keywords("hi")


def test_answer_from_audio_falls_back_to_buttons_when_transcription_fails(monkeypatch) -> None:
    prompt = question_prompt(NAME_ISSUE, "which_is_correct", "hi")
    seen = []

    def heard(text):
        def fake(audio, language, keywords=None, **settings):
            seen.append(keywords)
            if text is None:
                raise TranscribeError("transcribe failed: timed out")
            return Transcript(text=text, audio_ms=800, request_s=1.0)
        return fake

    monkeypatch.setattr(answers, "transcribe", heard("दूसरा"))
    assert answers.answer_from_audio(b"wav", prompt, "hi").option == 1 and seen == [None]  # no keywords for hi
    monkeypatch.setattr(answers, "transcribe", heard(None))
    failed = answers.answer_from_audio(b"wav", prompt, "hi")
    assert failed.action == "show_buttons" and failed.say == load_voice("hi").answers.buttons
    monkeypatch.setattr(answers, "transcribe", heard("हम्म"))
    assert answers.answer_from_audio(b"wav", prompt, "hi").action == "ask_again"
    assert answers.answer_from_audio(b"wav", prompt, "hi", earlier=["हम्म"]).action == "show_buttons"
