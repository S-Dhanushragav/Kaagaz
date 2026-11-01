"""The Ask fact check in Tamil, Telugu and Kannada: digits in each script, number words, lakh/thousand words, the
answer's script, eligibility claims (also with a name written in the language's script), overclaims and fees."""

import pytest

from agents.ask_check import Evidence, answer_numbers, check
from agents.speech import say_in_script
from rules.loader import load_schemes

SCHEMES = {s.id: s for s in load_schemes()}


@pytest.mark.parametrize("text,expected", [
    ("மாதம் ₹1,500 கிடைக்கும்.", {1500.0}),
    ("௨௧ வயது முதல் ௬௫ வயது வரை.", {21.0, 65.0}),  # Tamil digits
    ("ஐந்து திட்டங்கள், இருபது நாட்கள்.", {5.0, 20.0}),  # number words
    ("வருமானம் 2.5 லட்சத்துக்குள் இருக்க வேண்டும்.", {250000.0}),  # lakh with a case ending
    ("రెండు పథకాలు, పది రోజులు.", {2.0, 10.0}),
    ("౨౧ ఏళ్లు నిండినవారు.", {21.0}),  # Telugu digits
    ("ఆదాయం 2.5 లక్షల లోపు.", {250000.0}),
    ("21 వేలు", {21000.0}),
    ("ಮೂರು ದಾಖಲೆಗಳು, ಹದಿನೈದು ದಿನಗಳು.", {3.0, 15.0}),
    ("೬೫ ವರ್ಷ ಮೇಲ್ಪಟ್ಟವರು.", {65.0}),  # Kannada digits
    ("ಆದಾಯ 2 ಲಕ್ಷದ ಒಳಗೆ, ಶುಲ್ಕ 1,500 ರೂಪಾಯಿ.", {200000.0, 1500.0}),
])
def test_numbers_in_digits_and_words(text: str, expected: set[float]) -> None:
    assert answer_numbers(text) == expected


def test_a_number_no_tool_returned_is_caught_in_words_and_digits() -> None:
    ev = Evidence(used=[{"tool": "get_scheme_rules", "args": {}, "result": {"age_min": 21}}])
    assert not [f for f in check("௨௧ வயது ஆக வேண்டும்.", "ta", ev) if "numbers" in f]
    assert [f for f in check("முப்பது வயது ஆக வேண்டும்.", "ta", ev) if "numbers" in f]  # 30
    assert [f for f in check("ಕನಿಷ್ಠ ವಯಸ್ಸು ೩೦.", "kn", ev) if "numbers" in f]
    assert [f for f in check("కనీసం ముప్పై ఏళ్లు.", "te", ev) if "numbers" in f]


@pytest.mark.parametrize("language", ["ta", "te", "kn"])
def test_an_answer_in_english_is_not_accepted(language: str) -> None:
    failures = check("Women aged 21 to 65 can apply for this scheme on these documents.", language, Evidence(used=[]))
    assert any(f.startswith("Answer in") for f in failures)


def test_latin_names_in_a_tamil_answer_are_fine() -> None:
    failures = check("Savita Aditya Bhosale: ஆதார் அட்டையின் தெளிவான புகைப்படம் வேண்டும்.", "ta", Evidence(used=[]))
    assert not any(f.startswith("Answer in") for f in failures)


def _family(language: str, outcome: str) -> Evidence:
    names = ["Lata Aditya Bhosale", "लता आदित्य भोसले", say_in_script("लता आदित्य भोसले", language)]
    return Evidence(used=[{"tool": "get_member_results", "args": {}, "result": {"member_id": "r3"}}],
                    members={"r3": [*names, *(n.split()[0] for n in names)]},
                    outcomes={("r3", "ladki_bahin"): outcome})


@pytest.mark.parametrize("language,sentence", [
    ("ta", "Lata இந்த ஆவணங்களின்படி {scheme} திட்டத்துக்கு தகுதியானவர்."),
    ("ta", "லதாவுக்கு ஆவணங்களின்படி {scheme} திட்டத்துக்கு தகுதி உண்டு."),  # the name written in Tamil, with an ending
    ("te", "ఈ పత్రాల ప్రకారం Lata {scheme} పథకానికి అర్హురాలు."),
    ("kn", "ಈ ದಾಖಲೆಗಳ ಪ್ರಕಾರ ಲತಾ {scheme} ಯೋಜನೆಗೆ ಅರ್ಹರು."),
])
def test_a_wrong_eligibility_claim_is_caught(language: str, sentence: str) -> None:
    text = sentence.format(scheme=SCHEMES["ladki_bahin"].short[language])
    failures = check(text, language, _family(language, "not_eligible"))
    assert any("not eligible on these documents" in f for f in failures), failures


@pytest.mark.parametrize("language,sentence", [
    ("ta", "Lata இந்த ஆவணங்களின்படி {scheme} திட்டத்துக்கு தகுதியானவர். அலுவலகம் முடிவு செய்யும்."),
    ("te", "ఈ పత్రాల ప్రకారం Lata {scheme} పథకానికి అర్హురాలు. కార్యాలయం నిర్ణయిస్తుంది."),
    ("kn", "ಈ ದಾಖಲೆಗಳ ಪ್ರಕಾರ Lata {scheme} ಯೋಜನೆಗೆ ಅರ್ಹರು. ಕಚೇರಿ ನಿರ್ಧರಿಸುತ್ತದೆ."),
])
def test_a_right_eligibility_claim_on_these_documents_passes(language: str, sentence: str) -> None:
    text = sentence.format(scheme=SCHEMES["ladki_bahin"].short[language])
    failures = check(text, language, _family(language, "eligible_on_documents"))
    assert not any("eligible" in f or "promise" in f for f in failures), failures


@pytest.mark.parametrize("language,sentence", [
    ("ta", "Savita {scheme} திட்டத்துக்கு கண்டிப்பாக தகுதியானவர்."),
    ("te", "Savita కు {scheme} పథకం తప్పకుండా వస్తుంది, ఆమె అర్హురాలు."),
    ("kn", "Savita ಅವರಿಗೆ {scheme} ಯೋಜನೆ ಖಂಡಿತವಾಗಿ ಸಿಗುತ್ತದೆ."),
])
def test_promises_are_caught(language: str, sentence: str) -> None:
    text = sentence.format(scheme=SCHEMES["ladki_bahin"].short[language])
    assert any("promise" in f for f in check(text, language, Evidence(used=[])))


@pytest.mark.parametrize("language,text", [
    ("ta", "இந்தச் சான்றிதழ் இலவசம்."),
    ("te", "ఈ పత్రం ఉచితంగా ఇస్తారు."),
    ("kn", "ಈ ಪ್ರಮಾಣಪತ್ರ ಉಚಿತ."),
])
def test_never_free(language: str, text: str) -> None:
    assert any("free" in f for f in check(text, language, Evidence(used=[])))


@pytest.mark.parametrize("language,text", [
    ("ta", "இதற்குக் கட்டணம் செலுத்த வேண்டும்."),
    ("te", "దీనికి రుసుము చెల్లించాలి."),
    ("kn", "ಇದಕ್ಕೆ ಶುಲ್ಕ ಕಟ್ಟಬೇಕು."),
])
def test_a_fee_without_a_lookup_is_caught(language: str, text: str) -> None:
    assert any("No fee was looked up" in f for f in check(text, language, Evidence(used=[])))


@pytest.mark.parametrize("language,text", [
    ("ta", "இது பற்றி கட்டணத் தகவல் இல்லை: அலுவலகத்தில் கேளுங்கள்."),
    ("te", "రుసుము గురించి సమాచారం లేదు: కార్యాలయంలో అడగండి."),
    ("kn", "ಶುಲ್ಕದ ಬಗ್ಗೆ ಮಾಹಿತಿ ಇಲ್ಲ: ಕಚೇರಿಯಲ್ಲಿ ಕೇಳಿ."),
])
def test_saying_to_ask_about_the_fee_is_fine(language: str, text: str) -> None:
    assert not any("fee" in f.casefold() for f in check(text, language, Evidence(used=[])))


@pytest.mark.parametrize("language,text", [
    ("ta", "தஹசீல் அலுவலகத்தில் விண்ணப்பியுங்கள்."),
    ("te", "తహసీల్ కార్యాలయంలో దరఖాస్తు చేయండి."),
    ("kn", "ತಹಸೀಲ್ ಕಚೇರಿಯಲ್ಲಿ ಅರ್ಜಿ ಹಾಕಿ."),
])
def test_an_office_no_tool_returned_is_caught(language: str, text: str) -> None:
    assert any("tahsil" in f for f in check(text, language, Evidence(used=[])))


@pytest.mark.parametrize("language,text", [
    ("ta", "பிரதம மந்திரி கிசான் திட்டத்தில் பணம் கிடைக்கும்."),
    ("te", "రైతు బంధు పథకం గురించి చెప్పగలను."),
    ("kn", "ಗೃಹಲಕ್ಷ್ಮಿ ಯೋಜನೆಗೆ ಅರ್ಜಿ ಹಾಕಿ."),
])
def test_other_schemes_are_caught(language: str, text: str) -> None:
    assert any("Not one of the 5 schemes" in f for f in check(text, language, Evidence(used=[])))


@pytest.mark.parametrize("language", ["ta", "te", "kn"])
def test_our_scheme_names_are_not_other_schemes(language: str) -> None:
    word = {"ta": "திட்டம்", "te": "పథకం", "kn": "ಯೋಜನೆ"}[language]
    for s in load_schemes():
        text = f"{s.short[language]} ({s.short['en']}) {word}. {s.short[language]} {word}."
        assert not any("Not one of the 5 schemes" in f for f in check(text, language, Evidence(used=[]))), text


@pytest.mark.parametrize("language,text", [
    ("te", "లాడ్కీ బహిణ్ పథకంలో నెలకు ₹1,500 అందుతుంది."),  # బహిణ్ for బహీణ్
    ("kn", "ಪ್ರಧಾನಮಂತ್ರಿ ಉಜ್ವಲಾ ಯೋಜನೆಯ ಲಾಭ ಗ್ಯಾಸ್ ಸಂಪರ್ಕ."),  # ಉಜ್ವಲಾ for ಉಜ್ಜ್ವಲಾ
])
def test_a_near_spelling_of_our_scheme_is_still_ours(language: str, text: str) -> None:
    from agents.ask_check import _schemes_in

    assert not any("Not one of the 5 schemes" in f for f in check(text, language, Evidence(used=[])))
    assert _schemes_in(text)  # and it counts as that scheme for the eligibility check


def test_tamil_not_eligible_is_a_negative() -> None:
    from agents.ask_check import NEGATIVE

    assert NEGATIVE.search("லதா எந்த திட்டத்திற்கும் தகுதியானவர் அல்ல.")
