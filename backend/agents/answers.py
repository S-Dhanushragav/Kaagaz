"""Spoken answers to the family's questions: numbered options read aloud, answers matched by number only.

A question's options are read aloud with labels ("First: ... Second: ... Third: not sure."). A spoken answer
is matched to an option ONLY by number words ("second", "दूसरा", "दुसरे", "two", "2"), or to "not sure" by
not-sure words. Option texts (names, dates) are never matched: a heard name is not an answer. Anything else,
or more than one number, is no match: ask again once, then show buttons only. Deterministic. Vocabulary
lives in data/templates/voice/{en,hi,mr}.yaml (`answers`).
"""

import unicodedata
from typing import Any, Literal

from pydantic import BaseModel

from app.config import get_settings
from clients.transcribe import TranscribeError, transcribe
from schemas.fixes import PlannerIssue

from agents.speech import speech_text
from agents.tools import COMPARE_OPTIONS
from agents.voice import (document_names, documents_with_values, english_only, load_voice, member_text, question_text,
                          shown_value)

NOT_SURE = "not sure"
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
# long vowel -> short; anusvara, chandrabindu, nukta -> removed (NFD splits nukta letters like ड़ into ड + ़)
SPELLING = str.maketrans({"ी": "ि", "ू": "ु", "ई": "इ", "ऊ": "उ", "ं": None, "ँ": None, "़": None})


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
    `re`'s \\w would drop them). Spelling-tolerant: long and short vowels are the same (ी/ि, ू/ु, ई/इ, ऊ/उ),
    and anusvara, chandrabindu and nukta are ignored, as the ASR writes these inconsistently."""
    text = unicodedata.normalize("NFC", text).translate(DEVANAGARI_DIGITS).lower()
    text = unicodedata.normalize("NFD", text).translate(SPELLING)
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


def use_keywords(language: str) -> bool:
    """Keyword biasing per language (ASR_KEYWORD_LANGUAGES, default 'en': it hurt Hindi and Marathi)."""
    return language in {x.strip() for x in get_settings().asr_keyword_languages.split(",") if x.strip()}


class Prompt(BaseModel):
    options: list[str]  # canonical options (values, or same/different), 'not sure' last
    shown: list[str]  # each option as shown and said
    screen: str  # question, both spellings, numbered options (digits kept)
    speech: str  # short spoken prompt, numbers spelled out (TTS input)
    english_only: bool = False  # hi/mr: the values differ only in Latin script: the voice points to the screen


def question_prompt(issue: PlannerIssue, kind: str, language: str) -> Prompt:
    """The question names the documents; the numbered options carry the values. In Hindi and Marathi, a
    difference only in Latin script is not read out: the voice says the English spelling differs and asks the
    family to look at the screen, which shows both spellings."""
    t = load_voice(language)
    vocab = t.answers
    if kind == "which_is_correct":
        options = [*sorted(set(issue.values.values())), NOT_SURE]
        shown = [shown_value(v, issue, language) for v in options[:-1]] + [t.options[NOT_SURE]]
    else:
        options = [*COMPARE_OPTIONS, NOT_SURE]
        shown = [t.options[o] for o in options]
    question = question_text(issue, kind, language)
    numbered = [vocab.option.format(label=vocab.labels[i], option=o) for i, o in enumerate(shown)]
    screen = "\n".join([question, documents_with_values(issue, language), *numbered])
    latin_only = kind == "which_is_correct" and english_only(issue, language) and vocab.english_only is not None
    if latin_only:
        member, docs = member_text(issue, language), document_names(list(issue.documents.values()), language)
        stop = vocab.option.rstrip()[-1]  # the language's full stop ('.' or '।')
        labels = [vocab.option.format(label=vocab.labels[i], option=shown[i]) if i == len(shown) - 1
                  else f"{vocab.labels[i]}{stop}" for i in range(len(shown))]
        spoken = " ".join([vocab.english_only.format(member=member, documents=docs), *labels, vocab.instruction])
    else:
        spoken = " ".join([question, *numbered, vocab.instruction])
    return Prompt(options=options, shown=shown, screen=screen, speech=speech_text(spoken, language),
                  english_only=latin_only)


def answer_from_audio(audio: bytes, prompt: Prompt, language: str, earlier: list[str] | None = None,
                      **transcribe_settings: Any) -> AnswerResult:
    """Transcribe a spoken answer (interactive: 10 s timeout, one retry) and resolve it. `earlier`: transcripts
    of previous tries for this question. If transcription fails, show the buttons."""
    try:
        heard = transcribe(audio, language, keywords(prompt.options, language) if use_keywords(language) else None,
                           **transcribe_settings).text
    except TranscribeError:
        return AnswerResult(action="show_buttons", say=load_voice(language).answers.buttons)
    return resolve([*(earlier or []), heard], prompt.options, language)


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
