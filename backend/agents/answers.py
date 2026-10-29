"""Spoken answers to the family's questions: numbered options read aloud, answers matched by number only.

A question's options are read aloud with labels ("First: ... Second: ... Third: not sure."). A spoken answer
is matched to an option ONLY by number words ("second", "दूसरा", "दुसरे", "two", "2"), or to "not sure" by
not-sure words. Option texts (names, dates) are never matched: a heard name is not an answer. Anything else,
or more than one number, is no match: ask again once, then show buttons only. Deterministic. Vocabulary
lives in data/templates/voice/{en,hi,mr}.yaml (`answers`).
"""

import unicodedata
from typing import Literal

from pydantic import BaseModel

from agents.speech import speech_text
from agents.voice import load_voice

NOT_SURE = "not sure"
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


class Match(BaseModel):
    option: int | None  # 0-based index into the options, or None (no match)
    heard: str
    reason: str  # 'number', 'not sure', 'no number', 'several numbers', 'out of range'


class AnswerResult(BaseModel):
    action: Literal["answered", "ask_again", "show_buttons"]
    option: int | None = None
    say: str | None = None  # what to say next (retry or buttons line)
    attempts: list[Match] = []


def _normalize(text: str) -> str:
    """Lowercase, Devanagari digits -> ASCII, punctuation and symbols -> spaces (vowel signs are kept:
    `re`'s \\w would drop them)."""
    text = unicodedata.normalize("NFC", text).translate(DEVANAGARI_DIGITS).lower()
    text = "".join(" " if unicodedata.category(c)[0] in "PS" and c != "'" else c for c in text)
    return " ".join(text.split())


def _has_phrase(text: str, phrase: str) -> bool:
    """Whole-word (or whole-phrase) match, on whitespace boundaries."""
    return f" {_normalize(phrase)} " in f" {text} "


def number_vocabulary(language: str, n_options: int) -> list[list[str]]:
    """For each option index: the words that select it (the language's number words plus the digit)."""
    words = load_voice(language).answers.numbers
    return [[*words[i], str(i + 1)] for i in range(min(n_options, len(words)))]


def match_answer(transcript: str, options: list[str], language: str) -> Match:
    """Match a transcript to an option by number words or not-sure words only. The last option is 'not sure'."""
    text = _normalize(transcript)
    vocab = load_voice(language).answers
    not_sure_index = options.index(NOT_SURE) if NOT_SURE in options else None
    numbers = {i for i, words in enumerate(number_vocabulary(language, len(load_voice(language).answers.numbers)))
               if any(_has_phrase(text, w) for w in words)}
    unsure = any(_has_phrase(text, w) for w in vocab.not_sure)
    if unsure and not numbers:
        return Match(option=not_sure_index, heard=transcript, reason="not sure")
    if not numbers:
        return Match(option=None, heard=transcript, reason="no number")
    if len(numbers) > 1 or unsure:
        return Match(option=None, heard=transcript, reason="several numbers")
    (i,) = numbers
    if i >= len(options):
        return Match(option=None, heard=transcript, reason="out of range")
    return Match(option=i, heard=transcript, reason="number")


def keywords(options: list[str], language: str) -> list[str]:
    """Words to bias recognition toward: the number words for these options and the not-sure words."""
    vocab = load_voice(language).answers
    return [w for words in number_vocabulary(language, len(options)) for w in words if not w.isdigit()] + vocab.not_sure


def options_prompt(question: str, options_shown: list[str], language: str) -> str:
    """The question, then each option with its label, then how to answer (screen text; digits kept)."""
    vocab = load_voice(language).answers
    lines = [vocab.option.format(label=vocab.labels[i], option=o) for i, o in enumerate(options_shown)]
    return " ".join([question, *lines, vocab.instruction])


def options_speech(question: str, options_shown: list[str], language: str) -> str:
    """The same prompt as TTS input: numbers and dates spelled out."""
    return speech_text(options_prompt(question, options_shown, language), language)


def resolve(transcripts: list[str], options: list[str], language: str) -> AnswerResult:
    """The flow: the first matched answer wins; one retry after a miss; after two misses, buttons only."""
    vocab = load_voice(language).answers
    attempts = []
    for transcript in transcripts[:2]:
        m = match_answer(transcript, options, language)
        attempts.append(m)
        if m.option is not None:
            return AnswerResult(action="answered", option=m.option, attempts=attempts)
    if len(attempts) < 2:
        return AnswerResult(action="ask_again", say=vocab.retry, attempts=attempts)
    return AnswerResult(action="show_buttons", say=vocab.buttons, attempts=attempts)
