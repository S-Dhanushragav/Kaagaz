"""Spoken answers: matched by number words or not-sure words only; never by names; retry once, then buttons."""

import pytest

from agents.answers import NOT_SURE, keywords, match_answer, options_prompt, options_speech, resolve
from agents.voice import LANGUAGES, load_voice

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


@pytest.mark.parametrize("language", LANGUAGES)
def test_prompt_reads_numbered_options_and_keywords_cover_the_number_words(language: str) -> None:
    vocab = load_voice(language).answers
    prompt = options_prompt("Q?", ["A", "B", "not sure shown"], language)
    assert all(label in prompt for label in vocab.labels[:3]) and prompt.endswith(vocab.instruction)
    kw = keywords(NAMES, language)
    assert vocab.labels[0].lower() in [k.lower() for k in kw] and vocab.not_sure[0] in kw
    assert not any(k.isdigit() for k in kw)
    assert not any(name in kw for name in NAMES[:2])  # names are never keywords
    assert len(vocab.labels) == len(vocab.numbers) == 5
    for i, label in enumerate(vocab.labels):  # every label read aloud is itself a matching answer
        assert match_answer(label, ["a", "b", "c", "d", NOT_SURE], language).option == i


def test_spoken_prompt_spells_out_dates() -> None:
    speech = options_speech("Which is correct?", ["05/02/1981", "04/02/1981", "not sure"], "en")
    assert "five February nineteen hundred eighty-one" in speech and "1981" not in speech
