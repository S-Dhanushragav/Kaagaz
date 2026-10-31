"""Fact check for Ask Kaagaz answers, before anything is shown. Deterministic; no model calls.

An answer passes only if:
- every number in it (digits, ₹ amounts like ₹2,04,000 or ₹1.5 lakh, dates, and number words in en/hi/mr) appears in
  the tool results it was based on (or is the count of a list in them);
- every scheme it names is one of the 5 (a name before 'scheme'/'Yojana'/'योजना' that is not one of ours, or a
  well-known other scheme, fails);
- every specific office or service point it names (Tahsil, Aadhaar Seva Kendra, Aaple Sarkar, ...) appears in the
  office facts or plan it looked up; a fee is mentioned only if one was looked up (else only to say to ask), and
  never 'free';
- every claim that a member is (not) eligible matches get_member_results, says 'on these documents' and never goes
  further ('definitely', 'will get', ...);
- it is in the asked language, under ~100 words, and contains no ID number.
`check` returns the failures as short instructions for the model's one retry.
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable

from agents.voice import load_voice
from rules.loader import load_schemes
from vision.text import redact_identity_numbers

MAX_WORDS = 100
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
SENTENCE = re.compile(r"(?<=[.?!।])\s+|\n+")
WORD = re.compile(r"[\wऀ-ॿ]+(?:-[\wऀ-ॿ]+)*")
# 1,500 / 2,04,000 / 1.5 / 15 -> one number; a following lakh/thousand/crore multiplies it
NUMBER = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?(?:\s*(lakh|lakhs|लाख|thousand|हज़ार|हजार|crore|करोड़|करोड|कोटी))?",
                    re.IGNORECASE)
MULTIPLIER = {"lakh": 100000, "lakhs": 100000, "लाख": 100000, "thousand": 1000, "हज़ार": 1000, "हजार": 1000,
              "crore": 10_000_000, "करोड़": 10_000_000, "करोड": 10_000_000, "कोटी": 10_000_000}
# 'one'/'एक' double as 'a'; Hindi 'दो' is also 'give'
AMBIGUOUS_NUMBER_WORDS = {"one", "एक", "दो", "zero", "शून्य"}

# ---------- schemes ----------

OTHER_SCHEMES = [  # well-known schemes that are not among Kaagaz's 5 (any state or the centre)
    "pm kisan", "pm-kisan", "kisan samman", "किसान सम्मान", "ayushman", "आयुष्मान", "mgnrega", "nrega", "मनरेगा",
    "jan dhan", "जन धन", "जनधन", "atal pension", "अटल पेंशन", "अटल पेन्शन", "sukanya", "सुकन्या", "pmay",
    "pradhan mantri awas", "प्रधानमंत्री आवास", "प्रधान मंत्री आवास", "mudra", "मुद्रा", "ladli behna", "लाडली बहना",
    "ladli bahna", "kanyashree", "lakshmir bhandar", "gruha lakshmi", "griha lakshmi", "annapurna", "अन्नपूर्णा",
    "rythu", "kalaignar", "magalir", "orunodoi", "mahtari", "subhadra", "jan arogya", "जन आरोग्य", "namo shetkari",
    "नमो शेतकरी", "vishwakarma", "विश्वकर्मा", "shiv bhojan", "शिवभोजन", "kisan credit", "किसान क्रेडिट",
    "old age pension scheme", "indira gandhi", "इंदिरा गांधी", "ration card scheme", "antyodaya", "अंत्योदय",
]
SCHEME_WORD_EN = re.compile(r"((?:\b[A-Z][\w'-]*\s+){1,5})(?:Yojana|Yojna|Scheme|scheme|yojana)\b")
SCHEME_WORD_DEV = re.compile(r"(\S+)\s+(?:योजना|योजने|योजनेच|योजनेत|योजनेसाठी|योजनेची|योजनेचा|योजनेला|योजनेचे|योजनाओं|योजनांसाठी)")
EN_STOP = {"this", "that", "these", "those", "which", "what", "each", "any", "every", "the", "a", "an", "your", "other",
           "another", "government", "state", "central", "no", "some", "all", "one", "its", "their", "for", "of", "in",
           "kaagaz", "these", "five", "for", "maharashtra", "new", "same", "and", "or", "ask", "about", "my", "our"}
DEV_STOP = {"इस", "यह", "ये", "किस", "किसी", "इन", "उन", "कौन", "कौनसी", "कौन-सी", "कोई", "हर", "सभी", "सब", "अन्य",
            "दूसरी", "दूसरे", "इतर", "या", "ह्या", "त्या", "ही", "कोणती", "कोणत्या", "कोणत्याही", "कोणतीही",
            "प्रत्येक", "सर्व", "पाच", "पांच", "पाँच", "की", "के", "का", "आपकी", "तुमच्या", "इसी", "उस", "उसी", "एक",
            "नई", "नवी", "सरकारी", "राज्य", "केंद्र", "मेरी", "माझ्या", "आमच्या", "हमारी", "किन", "कोणत्याच", "इन्हीं",
            "5", "महाराष्ट्र", "महाराष्ट्रातील", "महाराष्ट्र की", "और", "आणि", "व", "किंवा", "या", "तो", "वह", "उसकी",
            "ती", "त्यांची", "त्यांच्या", "शासकीय", "सरकारच्या", "दुसऱ्या", "दुसरी", "नवीन",
            # postpositions and particles: Hindi "योजना" is also "plan" ("इसके लिए योजना कहती है")
            "लिए", "से", "में", "पर", "को", "ने", "भी", "तो", "ही", "है", "हैं", "आपकी", "आपके", "आपका", "हमारी",
            "साठी", "मध्ये", "ने", "चा", "ची", "चे", "तुमची", "तुमचा", "तुमच्या", "आमची", "कुटुंबाची", "यांची"}


@lru_cache
def _scheme_tokens() -> frozenset[str]:
    tokens: set[str] = set()
    for s in load_schemes():
        for name in [*s.name.values(), *s.short.values(), s.id.replace("_", " ")]:
            tokens |= {w.casefold() for w in WORD.findall(name)}
    tokens -= {"योजना", "yojana", "scheme", "pm"}
    return frozenset(tokens)


def _is_ours(words: Iterable[str]) -> bool:
    ours = _scheme_tokens()
    return any(w.casefold() in ours or w.casefold().rstrip("ीे") in ours for w in words)


def unknown_schemes(text: str) -> list[str]:
    low = text.casefold()
    found = [s for s in OTHER_SCHEMES if s in low]
    for m in SCHEME_WORD_EN.finditer(text):
        words = [w for w in WORD.findall(m.group(1)) if w.casefold() not in EN_STOP]
        if words and not _is_ours(words):
            found.append(" ".join(words))
    for m in SCHEME_WORD_DEV.finditer(text):
        word = m.group(1).strip("\"'“”‘’()")
        if word not in DEV_STOP and not word.isdigit() and not _is_ours([word]):
            found.append(word)
    return list(dict.fromkeys(found))


# ---------- offices ----------

OFFICE_TAGS: dict[str, list[str]] = {  # specific offices and service points; 'the office' alone is always fine
    "tahsil": ["tahsil", "tehsil", "tahasil", "तहसील", "तहसिल", "tahsildar", "तहसीलदार", "तहसिलदार"],
    "aadhaar_kendra": ["aadhaar seva kendra", "aadhaar kendra", "aadhaar centre", "aadhaar center",
                       "aadhaar enrolment centre", "आधार सेवा केंद्र", "आधार केंद्र", "आधार सेवा केंद्रात"],
    "aaple_sarkar": ["aaple sarkar", "aapale sarkar", "apale sarkar", "आपले सरकार", "setu", "सेतू", "सेतु"],
    "csc": ["csc", "common service", "कॉमन सर्विस", "जन सेवा केंद्र", "jan seva kendra"],
    "supply": ["supply office", "पुरवठा", "आपूर्ति", "rationing office", "ration office", "शिधावाटप", "rcms",
               "ration card management"],
    "sdo": ["sub-divisional", "sub divisional", "sdo", "deputy collector", "उपविभागीय", "उपजिल्हाधिकारी",
            "उप जिलाधिकारी", "प्रांत"],
    "collector": ["collector office", "district collector", "collectorate", "जिल्हाधिकारी कार्यालय",
                  "जिलाधिकारी कार्यालय", "कलेक्टर"],
    "uidai": ["uidai", "यूआयडीएआय", "यूआईडीएआई", "regional office", "प्रादेशिक कार्यालय", "क्षेत्रीय कार्यालय"],
    "panchayat": ["panchayat", "पंचायत", "gram sevak", "ग्रामसेवक", "ग्राम सेवक", "talathi", "तलाठी", "sarpanch",
                  "सरपंच"],
    "municipal": ["municipal", "corporation office", "नगरपालिका", "महानगरपालिका", "नगर परिषद", "नगरपरिषद"],
    "bank": ["bank", "बैंक", "बँक"],
    "post": ["post office", "डाकघर", "पोस्ट ऑफिस", "टपाल"],
    "gas": ["gas agency", "lpg distributor", "gas distributor", "गैस एजेंसी", "गॅस एजन्सी", "वितरक"],
    "anganwadi": ["anganwadi", "अंगणवाडी", "आंगनवाड़ी", "आंगनबाड़ी"],
    "social_welfare": ["social welfare", "समाज कल्याण", "समाजकल्याण", "mahadbt", "महाडीबीटी"],
    "police": ["police", "पोलीस", "पुलिस", "थाना"],
    "court": ["court", "न्यायालय", "कोर्ट"],
}


def office_tags(text: str) -> set[str]:
    low = text.casefold()
    return {tag for tag, words in OFFICE_TAGS.items()
            if any(re.search(rf"(?<![\wऀ-ॿ]){re.escape(w)}", low) for w in words)}


# ---------- fees ----------

FEE_WORDS = ["fee", "fees", "charge", "charges", "cost", "costs", "शुल्क", "फीस", "फी", "पैसे लगते", "पैसे लागतात"]
FREE_WORDS = ["free of cost", "for free", "is free", "there is no fee", "no fee for", "no fee to", "no charge", "costs nothing", "मुफ्त", "मुफ़्त",
              "निःशुल्क", "निशुल्क", "मोफत", "विनामूल्य", "कोई शुल्क नहीं", "शुल्क नाही", "शुल्क नहीं"]
UNSURE_WORDS = ["ask", "check", "confirm", "not know", "don't know", "do not know", "no information", "don't have",
                "do not have", "does not have", "not verified", "no verified", "not listed", "no fee is listed", "पूछ", "पुष्टि", "जानकारी नहीं", "पता नहीं", "मालूम नहीं", "विचार", "खात्री",
                "माहिती नाही", "माहीत नाही"]

# ---------- eligibility ----------

ELIGIBLE = re.compile(r"eligible|qualif(?:y|ies|ied)|पात्र(?!ता)|योग्य(?!ता)", re.IGNORECASE)  # not "eligibility"
NEGATIVE = re.compile(r"not eligible|ineligible|not qualify|n't qualify|not be eligible|isn't eligible|aren't eligible|"
                      r"cannot (?:apply|get)|अपात्र|पात्र नहीं|योग्य नहीं|पात्र नाही|पात्र ठरत नाही|पात्र नसल",
                      re.IGNORECASE)
NOT_YET = re.compile(r"\byet\b|first|until|after|once|अभी|पहले|जब तक|अजून|आधी|पर्यंत|नंतर", re.IGNORECASE)
QUALIFIER = re.compile(r"(?:on|from|by|based on|according to)\s+(?:these|the|your|their|this check's)\s+documents|"
                       r"documents show|दस्तावेज़ों के आधार पर|दस्तावेजों के आधार पर|कागज़ों के आधार पर|कागजों के आधार पर|"
                       r"दस्तावेज़ों से|दस्तावेजों से|दस्तावेज़ों के अनुसार|दस्तावेजों के अनुसार|कागदपत्रांनुसार|"
                       r"कागदपत्रांवरून|कागदपत्रांच्या आधारे|कागदपत्रांच्या आधारावर", re.IGNORECASE)
OVERCLAIM = re.compile(r"definitely|certainly|guarantee|surely|for sure|100\s*%|will (?:definitely |surely )?(?:get|receive)|"
                       r"निश्चित|पक्का|पक्की|ज़रूर|जरूर|गारंटी|अवश्य|मिलेगा ही|मिल जाएगा|मिल जाएगी|नक्की|हमखास|"
                       r"मिळेलच|मिळणारच", re.IGNORECASE)
REFUSAL = re.compile(r"can't|cannot|can not|won't|will not|not able to|unable to|नहीं कर सकता|नहीं कह सकता|"
                     r"नहीं बता सकता|शकत नाही|सांगू शकत नाही", re.IGNORECASE)
EVERYONE = re.compile(r"everyone|everybody|all (?:of )?(?:you|the members|members|family)|whole family|सभी|सब लोग|"
                      r"पूरा परिवार|सर्व|सगळे|सगळ्या|सर्वजण|संपूर्ण कुटुंब", re.IGNORECASE)


@dataclass
class Evidence:
    """What the answer may use: the tool results it was based on, plus the family's names and results."""

    used: list[dict[str, Any]]  # {"tool", "args", "result"}
    members: dict[str, list[str]] = field(default_factory=dict)  # member id -> name variants (full and first names)
    outcomes: dict[tuple[str, str], str] = field(default_factory=dict)  # (member id, scheme id) -> outcome

    def text(self, tools: Iterable[str] | None = None) -> str:
        keep = [u["result"] for u in self.used if tools is None or u["tool"] in tools]
        return json.dumps(keep, ensure_ascii=False)


def _numbers(text: str) -> set[float]:
    out = set()
    for m in NUMBER.finditer(text.translate(DEVANAGARI_DIGITS)):
        raw = m.group(0)
        digits = re.match(r"\d+(?:,\d+)*(?:\.\d+)?", raw).group(0).replace(",", "")
        value = float(digits)
        if m.group(1):
            value *= MULTIPLIER[m.group(1).casefold()] if m.group(1).casefold() in MULTIPLIER else MULTIPLIER[m.group(1)]
        out.add(round(value, 2))
    return out


@lru_cache
def _number_words() -> dict[str, int]:
    words: dict[str, int] = {}
    for language in ("en", "hi", "mr"):
        for n, w in enumerate(load_voice(language).numbers.words):
            if w not in AMBIGUOUS_NUMBER_WORDS and n >= 2:
                words[w.casefold()] = n
    return words


def answer_numbers(text: str) -> set[float]:
    found = _numbers(text)
    table = _number_words()
    for w in WORD.findall(text.casefold()):
        if w in table:
            found.add(float(table[w]))
    return found


def allowed_numbers(used: list[dict[str, Any]]) -> set[float]:
    allowed = _numbers(json.dumps([u["result"] for u in used], ensure_ascii=False))

    def counts(x: Any) -> None:
        if isinstance(x, list):
            allowed.add(float(len(x)))
            for y in x:
                counts(y)
        elif isinstance(x, dict):
            for y in x.values():
                counts(y)

    for u in used:
        counts(u["result"])
    allowed.add(float(len(load_schemes())))  # "the 5 schemes"
    return allowed


def _mentions(sentence: str, names: list[str]) -> bool:
    low = sentence.casefold()
    return any(re.search(rf"(?<![\wऀ-ॿ]){re.escape(n.casefold())}", low) for n in names if n)


def _schemes_in(sentence: str) -> list[str]:
    low = sentence.casefold()
    out = []
    for s in load_schemes():
        names = [*s.name.values(), *s.short.values()]
        if any(n.casefold() in low for n in names):
            out.append(s.id)
    return out


def eligibility_failures(text: str, ev: Evidence) -> list[str]:
    failures = []
    for sentence in [s for s in SENTENCE.split(text) if s.strip()]:
        schemes = _schemes_in(sentence)
        if OVERCLAIM.search(sentence) and (ELIGIBLE.search(sentence) or schemes) and not REFUSAL.search(sentence):
            failures.append("Never promise a benefit or say 'definitely': say only 'eligible on these documents'; "
                            "the office decides.")
        if not ELIGIBLE.search(sentence) or (REFUSAL.search(sentence) and not ev.outcomes):
            continue
        negative = bool(NEGATIVE.search(sentence)) or bool(REFUSAL.search(sentence))
        members = [m for m, names in ev.members.items() if _mentions(sentence, names)]
        if EVERYONE.search(sentence) and not negative and ev.members:
            members = list(ev.members)
            ok = all(any(o == "eligible_on_documents" for (mm, _), o in ev.outcomes.items() if mm == m) for m in members)
            if not ok:
                failures.append("Not everyone is eligible on these documents: say only what get_member_results says "
                                "for each member.")
                continue
        if not members:
            continue
        if not ev.outcomes:
            failures.append("Look up get_member_results before saying whether a member is eligible.")
            continue
        for m in members:
            pairs = [(m, s) for s in schemes] or [(m, s) for (mm, s) in ev.outcomes if mm == m]
            outcomes = [ev.outcomes.get(p) for p in pairs]
            if negative:
                bad = [p for p, o in zip(pairs, outcomes) if o not in ("not_eligible",)
                       and not (NOT_YET.search(sentence) and o in ("blocked_by_issues", "check_at_office"))]
                if schemes and bad:
                    failures.append(f"{m} is not 'not eligible' for {', '.join(s for _, s in bad)}: "
                                    "use get_member_results.")
            else:
                if schemes and any(o != "eligible_on_documents" for o in outcomes):
                    wrong = [s for (_, s), o in zip(pairs, outcomes) if o != "eligible_on_documents"]
                    failures.append(f"{m} is not eligible on these documents for {', '.join(wrong)} "
                                    "(see get_member_results).")
                elif not schemes and "eligible_on_documents" not in outcomes:
                    failures.append(f"{m} is not eligible on these documents for any scheme (see get_member_results).")
                elif not QUALIFIER.search(sentence):
                    failures.append("When a member is eligible, say 'eligible on these documents' (the office decides).")
    return list(dict.fromkeys(failures))


def check(text: str, language: str, ev: Evidence) -> list[str]:
    """The failures of an answer (empty: it may be shown)."""
    failures: list[str] = []
    if redact_identity_numbers(text) != text:
        failures.append("Never write an ID number.")
    extra = sorted(answer_numbers(text) - allowed_numbers(ev.used))
    if extra:
        shown = ", ".join(f"{x:g}" for x in extra)
        failures.append(f"These numbers are not in the tool results: {shown}. Use only numbers a tool returned "
                        "(digits), or leave them out.")
    other = unknown_schemes(text)
    if other:
        failures.append(f"Not one of the 5 schemes: {', '.join(other)}. Name only Kaagaz's 5 schemes; for others reply "
                        "with kind out_of_scope.")
    offices = office_tags(text) - office_tags(ev.text(("get_office_facts", "get_plan")))
    if offices:
        failures.append(f"These offices are not in get_office_facts or get_plan: {', '.join(sorted(offices))}. Name only "
                        "offices those tools returned, or say to ask at the office.")
    low = text.casefold()
    looked_up_fee = '"fee": {' in ev.text(("get_office_facts", "get_plan"))
    if any(w in low for w in FREE_WORDS):  # no procedure in data/fixes is free
        failures.append("Never say something is free or has no fee: Kaagaz has no such information.")
    elif any(re.search(rf"(?<![\wऀ-ॿ]){re.escape(w)}(?![\wऀ-ॿ])", low) for w in FEE_WORDS) \
            and not looked_up_fee:
        fee_sentences = [s for s in SENTENCE.split(text)
                         if any(w in s.casefold() for w in FEE_WORDS)]
        if any(not any(u in s.casefold() for u in UNSURE_WORDS) for s in fee_sentences):
            failures.append("No fee was looked up: say Kaagaz has no fee information and to ask at the office.")
    failures += eligibility_failures(text, ev)
    letters = len(DEVANAGARI.findall(text)) + len(LATIN.findall(text))
    if letters:
        share = len(DEVANAGARI.findall(text)) / letters
        if language in ("hi", "mr") and share < 0.5:
            failures.append(f"Answer in {'Hindi' if language == 'hi' else 'Marathi'} (Devanagari script).")
        if language == "en" and share > 0.3:
            failures.append("Answer in English.")
    if len(WORD.findall(text)) > MAX_WORDS:
        failures.append("Too long: answer in under 80 words.")
    if not text.strip():
        failures.append("The answer is empty.")
    return failures
