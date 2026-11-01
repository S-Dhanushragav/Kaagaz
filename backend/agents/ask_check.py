"""Fact check for Ask Kaagaz answers, before anything is shown. Deterministic; no model calls.

An answer passes only if:
- every number in it (digits in any of the app's scripts, ₹ amounts like ₹2,04,000 or ₹1.5 lakh, dates, and number
  words in every language) appears in
  the tool results it was based on (or is the count of a list in them);
- every scheme it names is one of the 5 (a name before 'scheme'/'Yojana'/'योजना' that is not one of ours, or a
  well-known other scheme, fails);
- every specific office or service point it names (Tahsil, Aadhaar Seva Kendra, Aaple Sarkar, ...) appears in the
  office facts or plan it looked up; a fee is mentioned only if one was looked up (else only to say to ask), and
  never 'free';
- every claim that a member is (not) eligible matches get_member_results, says 'on these documents' and never goes
  further ('definitely', 'will get', ...);
- it is in the asked language (its own script), under ~100 words, names the app as the UI does, and contains no ID
  number.
Tamil, Telugu and Kannada have their own word lists below (eligibility, offices, fees, schemes); Dravidian words take
endings, so some of their lists match a stem (left boundary only).
`check` returns the failures as short instructions for the model's one retry.
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable

from rapidfuzz import fuzz

from agents.ask_tools import load_ask
from agents.voice import load_voice
from schemas.languages import ENGLISH_NAMES, INDIC, LANGUAGES, SCRIPT
from rules.loader import load_schemes
from vision.text import redact_identity_numbers

MAX_WORDS = 100
SCRIPT_NAMES = {"hi": "Devanagari", "mr": "Devanagari", "ta": "Tamil", "te": "Telugu", "kn": "Kannada"}
# Devanagari, Tamil, Telugu and Kannada digits -> 0-9
INDIC_DIGITS = str.maketrans("०१२३४५६७८९௦௧௨௩௪௫௬௭௮௯౦౧౨౩౪౫౬౭౮౯೦೧೨೩೪೫೬೭೮೯", "0123456789" * 4)
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
SENTENCE = re.compile(r"(?<=[.?!।])\s+|\n+")
WORD = re.compile(rf"[\w{INDIC}]+(?:-[\w{INDIC}]+)*")
NOT_LETTER = rf"(?<![\w{INDIC}])"  # left word boundary in any script
# 1,500 / 2,04,000 / 1.5 / 15 -> one number; a following lakh/thousand/crore (or a word starting like one) multiplies it
NUMBER = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?(?:\s*([^\s\d,.;:!?()\[\]]+))?")
MULTIPLIER = {"lakh": 100000, "लाख": 100000, "thousand": 1000, "हज़ार": 1000, "हजार": 1000, "crore": 10_000_000,
              "करोड़": 10_000_000, "करोड": 10_000_000, "कोटी": 10_000_000,
              "லட்ச": 100000, "இலட்ச": 100000, "ஆயிர": 1000, "கோடி": 10_000_000,
              "లక్ష": 100000, "వేల": 1000, "వెయ్య": 1000, "కోట": 10_000_000,
              "ಲಕ್ಷ": 100000, "ಸಾವಿರ": 1000, "ಕೋಟಿ": 10_000_000}
# 'one'/'एक' double as 'a'; Hindi 'दो' is also 'give'; Tamil 'ஒன்று' is also 'something'
AMBIGUOUS_NUMBER_WORDS = {"one", "एक", "दो", "zero", "शून्य", "ஒன்று", "ஒரு", "ஒன்னு", "பூஜ்ஜியம்", "పూజ్యం", "సున్నా",
                          "ఒకటి", "ఒక", "ಒಂದು", "ಸೊನ್ನೆ"}

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
# Tamil திட்டம் (also 'plan'), Telugu పథకం, Kannada ಯೋಜನೆ, and the transliterated యోజన / யோஜனா, with their endings
SCHEME_WORD_DRAVIDIAN = re.compile(r"(\S+)\s+(?:திட்ட\S*|யோஜனா\S*|పథక\S*|యోజన\S*|ಯೋಜನೆ\S*|ಯೋಜನಾ\S*)")
DRAVIDIAN_STOP = {
    "இந்த", "அந்த", "எந்த", "இந்தத்", "அந்தத்", "எந்தத்", "ஒவ்வொரு", "மற்ற", "வேறு", "ஐந்து", "அரசு", "மாநில", "மத்திய",
    "புதிய", "உங்கள்", "உங்களது", "எங்கள்", "செயல்", "சரிசெய்யும்", "அரசின்", "மகாராஷ்டிரா", "மகாராஷ்டிர", "ஒரு",
    "ఈ", "ఆ", "ఏ", "ప్రతి", "ఇతర", "మరో", "ఐదు", "ప్రభుత్వ", "రాష్ట్ర", "కేంద్ర", "కొత్త", "ఏదైనా", "మీ", "మా", "ఒక",
    "మహారాష్ట్ర", "ಈ", "ಆ", "ಯಾವ", "ಪ್ರತಿ", "ಇತರ", "ಬೇರೆ", "ಐದು", "ಸರ್ಕಾರಿ", "ರಾಜ್ಯ", "ಕೇಂದ್ರ", "ಹೊಸ", "ಯಾವುದೇ",
    "ನಿಮ್ಮ", "ನಮ್ಮ", "ಒಂದು", "ಮಹಾರಾಷ್ಟ್ರ", "ಸರ್ಕಾರದ", "5"}
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
def _plain(text: str) -> str:
    """Without zero-width (non-)joiners: Telugu/Kannada words may or may not carry them (శ్రావణ్‌బాళ్ = శ్రావణ్బాళ్)."""
    return text.replace("‌", "").replace("‍", "")


def _scheme_tokens() -> frozenset[str]:
    tokens: set[str] = set()
    for s in load_schemes():
        for name in [*s.name.values(), *s.short.values(), s.id.replace("_", " ")]:
            tokens |= {w.casefold() for w in WORD.findall(_plain(name))}
    tokens -= {"योजना", "yojana", "scheme", "pm"}
    return frozenset(tokens)


def _dravidian(word: str) -> bool:
    return bool(re.search(r"[\u0b80-\u0cff]", word))


def _close(word: str, name_word: str) -> bool:
    """A Tamil/Telugu/Kannada word that is a near spelling of a name word (బహిణ్ / బహీణ్), maybe with an ending."""
    return len(name_word) >= 3 and fuzz.ratio(word[:len(name_word) + 1], name_word) >= 80


def _is_ours(words: Iterable[str]) -> bool:
    ours = _scheme_tokens()
    if any(w.casefold() in ours or w.casefold().rstrip("ीे") in ours for w in words):
        return True
    return any(_close(w, t) for w in words if _dravidian(w) for t in ours if _dravidian(t))


def unknown_schemes(text: str) -> list[str]:
    text = _plain(text)
    low = text.casefold()
    found = [s for s in OTHER_SCHEMES if s in low]
    for m in SCHEME_WORD_EN.finditer(text):
        words = [w for w in WORD.findall(m.group(1)) if w.casefold() not in EN_STOP]
        if words and not _is_ours(words):
            found.append(" ".join(words))
    for m in SCHEME_WORD_DEV.finditer(text):
        word = m.group(1).strip("\"'“”‘’().,।")
        if word not in DEV_STOP and not word.isdigit() and not _is_ours([word]):
            found.append(word)
    for m in SCHEME_WORD_DRAVIDIAN.finditer(text):
        word = m.group(1).strip("\"'“”‘’(),:.।-")
        if word and word not in DRAVIDIAN_STOP and not word.isdigit() and not _is_ours([word]):
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


# Tamil, Telugu and Kannada names of the same offices (Maharashtra's offices transliterated, or the usual term)
for _tag, _words in {
    "tahsil": ["தஹசீல்", "தாசில்தார்", "தஹசில்", "తహసీల్", "తహసిల్", "ತಹಸೀಲ್", "ತಹಶೀಲ್", "ತಹಸಿಲ್"],
    "aadhaar_kendra": ["ஆதார் சேவை மைய", "ஆதார் மைய", "ఆధార్ సేవా కేంద్ర", "ఆధార్ కేంద్ర", "ಆಧಾರ್ ಸೇವಾ ಕೇಂದ್ರ", "ಆಧಾರ್ ಕೇಂದ್ರ"],
    "aaple_sarkar": ["ஆப்லே சர்கார்", "சேது", "ఆప్లే సర్కార్", "సేతు", "ಆಪ್ಲೆ ಸರ್ಕಾರ್", "ಸೇತು"],
    "csc": ["பொது சேவை மைய", "కామన్ సర్వీస్", "మీసేవ", "ಕಾಮನ್ ಸರ್ವಿಸ್", "ಸಾಮಾನ್ಯ ಸೇವಾ ಕೇಂದ್ರ"],
    "supply": ["வழங்கல்", "ரேஷன் அலுவலக", "సరఫరా", "రేషన్ కార్యాలయ", "ಸರಬರಾಜು", "ರೇಷನ್ ಕಚೇರಿ", "ಆಹಾರ ಇಲಾಖೆ"],
    "sdo": ["உதவி ஆட்சியர்", "துணை ஆட்சியர்", "கோட்டாட்சியர்", "சப் டிவிஷனல்", "సబ్ డివిజనల్", "డిప్యూటీ కలెక్టర్", "రెవెన్యూ డివిజనల్", "ಉಪವಿಭಾಗ", "ಉಪ ವಿಭಾಗ", "ಸಹಾಯಕ ಆಯುಕ್ತ", "ಉಪ ಜಿಲ್ಲಾಧಿಕಾರಿ", "ಡೆಪ್ಯುಟಿ ಕಲೆಕ್ಟರ್"],
    "collector": ["மாவட்ட ஆட்சியர்", "கலெக்டர் அலுவலக", "జిల్లా కలెక్టర్", "కలెక్టరేట్", "ಜಿಲ್ಲಾಧಿಕಾರಿಗಳ ಕಚೇರಿ", "ಡಿಸಿ ಕಚೇರಿ"],
    "uidai": ["யுஐடிஏஐ", "மண்டல அலுவலக", "பிராந்திய அலுவலக", "యూఐడీఏఐ", "ప్రాంతీయ కార్యాలయ", "ಯುಐಡಿಎಐ", "ಪ್ರಾದೇಶಿಕ ಕಚೇರಿ"],
    "panchayat": ["பஞ்சாயத்து", "ஊராட்சி", "தலாட்டி", "கிராம நிர்வாக", "పంచాయతీ", "సర్పంచ్", "తలాటి", "ಪಂಚಾಯತ್", "ಪಂಚಾಯಿತಿ", "ತಲಾಠಿ", "ಗ್ರಾಮ ಲೆಕ್ಕಾಧಿಕಾರಿ"],
    "municipal": ["நகராட்சி", "மாநகராட்சி", "మున్సిపల్", "పురపాలక", "ನಗರಸಭೆ", "ಪುರಸಭೆ", "ಮಹಾನಗರ ಪಾಲಿಕೆ"],
    "bank": ["வங்கி", "బ్యాంక్", "బ్యాంకు", "ಬ್ಯಾಂಕ್"],
    "post": ["தபால் நிலைய", "அஞ்சல்", "పోస్ట్ ఆఫీస్", "తపాలా", "ಅಂಚೆ"],
    "gas": ["கேஸ் ஏஜென்சி", "எரிவாயு முகவ", "గ్యాస్ ఏజెన్సీ", "ಗ್ಯಾಸ್ ಏಜೆನ್ಸಿ"],
    "anganwadi": ["அங்கன்வாடி", "అంగన్వాడీ", "ಅಂಗನವಾಡಿ"],
    "social_welfare": ["சமூக நல", "సాంఘిక సంక్షేమ", "ಸಮಾಜ ಕಲ್ಯಾಣ"],
    "police": ["காவல் நிலைய", "போலீஸ்", "పోలీస్", "ಪೊಲೀಸ್"],
    "court": ["நீதிமன்ற", "கோர்ட்", "కోర్టు", "న్యాయస్థాన", "ನ್ಯಾಯಾಲಯ", "ಕೋರ್ಟ್"],
}.items():
    OFFICE_TAGS[_tag] += _words


def office_tags(text: str) -> set[str]:
    low = text.casefold()
    return {tag for tag, words in OFFICE_TAGS.items()
            if any(re.search(NOT_LETTER + re.escape(w), low) for w in words)}


# ---------- fees ----------

FEE_WORDS = ["fee", "fees", "charge", "charges", "cost", "costs", "शुल्क", "फीस", "फी", "पैसे लगते", "पैसे लागतात"]
FEE_STEMS = ["கட்டண", "ఫీజు", "రుసుము", "రుసుం", "ಶುಲ್ಕ", "ಫೀಸ್"]  # Tamil, Telugu, Kannada: with any ending
FREE_WORDS = ["free of cost", "for free", "is free", "there is no fee", "no fee for", "no fee to", "no charge", "costs nothing", "मुफ्त", "मुफ़्त",
              "निःशुल्क", "निशुल्क", "मोफत", "विनामूल्य", "कोई शुल्क नहीं", "शुल्क नाही", "शुल्क नहीं", "இலவச",
              "கட்டணம் இல்லை", "கட்டணமில்லை", "ఉచిత", "రుసుము లేదు", "ఫీజు లేదు", "ಉಚಿತ", "ಶುಲ್ಕ ಇಲ್ಲ", "ಶುಲ್ಕವಿಲ್ಲ"]
UNSURE_WORDS = ["ask", "check", "confirm", "not know", "don't know", "do not know", "no information", "don't have",
                "do not have", "does not have", "not verified", "no verified", "not listed", "no fee is listed", "पूछ", "पुष्टि", "जानकारी नहीं", "पता नहीं", "मालूम नहीं", "विचार", "खात्री",
                "माहिती नाही", "माहीत नाही", "கேளுங்கள்", "தெரியாது", "தகவல் இல்லை", "உறுதி செய்",
                "అడగండి", "తెలియదు", "సమాచారం లేదు", "నిర్ధారించ", "ಕೇಳಿ", "ಗೊತ್ತಿಲ್ಲ", "ಮಾಹಿತಿ ಇಲ್ಲ", "ಖಚಿತಪಡಿಸ"]

# ---------- eligibility ----------

ELIGIBLE = re.compile(r"eligible|qualif(?:y|ies|ied)|पात्र(?!ता)|योग्य(?!ता)|"  # not "eligibility"
                      r"தகுதி|అర్హ|ಅರ್ಹ", re.IGNORECASE)  # ta/te/kn: 'eligibility' too (stricter, never looser)
NEGATIVE = re.compile(r"not eligible|ineligible|not qualify|n't qualify|not be eligible|isn't eligible|aren't eligible|"
                      r"cannot (?:apply|get)|अपात्र|पात्र नहीं|योग्य नहीं|पात्र नाही|पात्र ठरत नाही|पात्र नसल|"
                      r"தகுதி இல்லை|தகுதியில்லை|தகுதியற்ற|தகுதி பெறவில்லை|தகுதி கிடையாது|தகுதி\S*\s+அல்ல|"
                      r"అర్హత లేదు|అర్హులు కాదు|అర్హులు కారు|అనర్హ|అర్హత లేని|"
                      r"ಅರ್ಹತೆ ಇಲ್ಲ|ಅರ್ಹರಲ್ಲ|ಅನರ್ಹ|ಅರ್ಹರಾಗಿಲ್ಲ|ಅರ್ಹತೆಯಿಲ್ಲ", re.IGNORECASE)
NOT_YET = re.compile(r"\byet\b|first|until|after|once|अभी|पहले|जब तक|अजून|आधी|पर्यंत|नंतर|"
                     r"இன்னும்|முதலில்|வரை|பிறகு|ఇంకా|ముందు|వరకు|తర్వాత|ಇನ್ನೂ|ಮೊದಲು|ವರೆಗೆ|ನಂತರ", re.IGNORECASE)
QUALIFIER = re.compile(r"(?:on|from|by|based on|according to)\s+(?:these|the|your|their|this check's)\s+documents|"
                       r"documents show|दस्तावेज़ों के आधार पर|दस्तावेजों के आधार पर|कागज़ों के आधार पर|कागजों के आधार पर|"
                       r"दस्तावेज़ों से|दस्तावेजों से|दस्तावेज़ों के अनुसार|दस्तावेजों के अनुसार|कागदपत्रांनुसार|"
                       r"कागदपत्रांवरून|कागदपत्रांच्या आधारे|कागदपत्रांच्या आधारावर|"
                       r"ஆவணங்களின்படி|ஆவணங்களின் படி|ஆவணப்படி|ஆவணங்களின் அடிப்படையில்|ஆவணங்களைப் பொறுத்து|"
                       r"(?:పత్రాల|డాక్యుమెంట్ల|దస్తావేజుల)\s*(?:ప్రకారం|ఆధారంగా)|"
                       r"(?:ದಾಖಲೆಗಳ|ದಾಖಲಾತಿಗಳ)\s*(?:ಪ್ರಕಾರ|ಆಧಾರ)", re.IGNORECASE)
OVERCLAIM = re.compile(r"definitely|certainly|guarantee|surely|for sure|100\s*%|will (?:definitely |surely )?(?:get|receive)|"
                       r"निश्चित|पक्का|पक्की|ज़रूर|जरूर|गारंटी|अवश्य|मिलेगा ही|मिल जाएगा|मिल जाएगी|नक्की|हमखास|"
                       r"मिळेलच|मिळणारच|கண்டிப்பாக|உத்தரவாத|நிச்சயமாக (?:கிடை|தகுதி)|உறுதியாக (?:கிடை|தகுதி)|"
                       r"తప్పకుండా|గ్యారంటీ|హామీ|ఖచ్చితంగా (?:వస్తుంది|లభిస్తుంది|అర్హ)|"
                       r"ಖಂಡಿತ(?:ವಾಗಿ)? (?:ಸಿಗ|ಅರ್ಹ)|ಗ್ಯಾರಂಟಿ|ಖಾತರಿ|ಸಿಕ್ಕೇ ಸಿಗುತ್ತ", re.IGNORECASE)
REFUSAL = re.compile(r"can't|cannot|can not|won't|will not|not able to|unable to|नहीं कर सकता|नहीं कह सकता|"
                     r"नहीं बता सकता|शकत नाही|सांगू शकत नाही|முடியாது|చెప్పలేను|చేయలేను|కుదరదు|ಹೇಳಲಾರೆ|"
                     r"ಸಾಧ್ಯವಿಲ್ಲ", re.IGNORECASE)
EVERYONE = re.compile(r"everyone|everybody|all (?:of )?(?:you|the members|members|family)|whole family|सभी|सब लोग|"
                      r"पूरा परिवार|सर्व|सगळे|सगळ्या|सर्वजण|संपूर्ण कुटुंब|எல்லோரும்|எல்லாரும்|அனைவரும்|"
                      r"முழு குடும்ப|అందరూ|అందరికీ|మొత్తం కుటుంబ|ಎಲ್ಲರೂ|ಎಲ್ಲರಿಗೂ|ಇಡೀ ಕುಟುಂಬ", re.IGNORECASE)


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
    for m in NUMBER.finditer(text.translate(INDIC_DIGITS)):
        raw = m.group(0)
        digits = re.match(r"\d+(?:,\d+)*(?:\.\d+)?", raw).group(0).replace(",", "")
        value = float(digits)
        word = (m.group(1) or "").casefold()
        value *= next((v for k, v in MULTIPLIER.items() if word.startswith(k)), 1)  # lakhs, லட்சம், ಲಕ್ಷದ ...
        out.add(round(value, 2))
    return out


@lru_cache
def _number_words() -> dict[str, int]:
    words: dict[str, int] = {}
    for language in LANGUAGES:
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
    if any(re.search(NOT_LETTER + re.escape(n.casefold()), low) for n in names if n):
        return True
    # a name written in Tamil/Telugu/Kannada script: a word close to one of the name's variants there (transliterations
    # differ, and the word may carry an ending)
    words = [w for w in WORD.findall(low) if not LATIN.search(w) and not DEVANAGARI.search(w)]
    variants = [n for n in names if n and not LATIN.search(n) and not DEVANAGARI.search(n) and " " not in n]
    return any(fuzz.ratio(w[:len(v) + 1], v) >= 80 for w in words for v in variants if len(v) >= 3)


def _schemes_in(sentence: str) -> list[str]:
    low = _plain(sentence).casefold()
    out = []
    words = [w for w in WORD.findall(low) if _dravidian(w)]
    for s in load_schemes():
        names = [*s.name.values(), *s.short.values()]
        near = [_plain(n).split() for n in s.short.values() if _dravidian(n)]
        if any(_plain(n).casefold() in low for n in names) or \
                any(all(any(_close(w, nw) for w in words) for nw in name) for name in near):
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
    elif (any(re.search(NOT_LETTER + re.escape(w) + rf"(?![\w{INDIC}])", low) for w in FEE_WORDS)
          or any(re.search(NOT_LETTER + re.escape(w), low) for w in FEE_STEMS)) and not looked_up_fee:
        fee_sentences = [s for s in SENTENCE.split(text)
                         if any(w in s.casefold() for w in [*FEE_WORDS, *FEE_STEMS])]
        if any(not any(u in s.casefold() for u in UNSURE_WORDS) for s in fee_sentences):
            failures.append("No fee was looked up: say Kaagaz has no fee information and to ask at the office.")
    failures += eligibility_failures(text, ev)
    brand = load_ask(language).brand
    if any(re.search(rx, text) for rx in load_ask(language).brand_wrong):
        failures.append(f"The app's name is written {brand} in this language: never any other spelling.")
    letters = len(re.findall(rf"[{INDIC}A-Za-z]", text))
    if letters:
        own = len(re.findall(f"[{SCRIPT[language]}]", text)) / letters
        if language == "en" and own < 0.7:
            failures.append("Answer in English.")
        elif language != "en" and own < 0.5:  # names in Latin letters are allowed; the rest is in the script
            failures.append(f"Answer in {ENGLISH_NAMES[language]} ({SCRIPT_NAMES[language]} script).")
    if len(WORD.findall(text)) > MAX_WORDS:
        failures.append("Too long: answer in under 80 words.")
    if not text.strip():
        failures.append("The answer is empty.")
    return failures
