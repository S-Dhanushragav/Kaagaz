"""Extra names and labels for the v2 evaluation set (EV001-EV030). The v1 lists in names.py are
unchanged so HH001-HH010 stay reproducible.

Rare names and unusual spellings are included on purpose: the reader should copy them exactly, and
the eval measures when it "corrects" them to a more common word.
"""

from synthetic.names import CASTE_CATEGORIES, FEMALE_NAMES, MALE_NAMES, SURNAMES, VARIANTS, Pair

RARE_MALE_NAMES = [
    Pair("ऋग्वेद", "Rugved"), Pair("हृषीकेश", "Hrishikesh"), Pair("श्रीनिवास", "Shrinivas"),
    Pair("क्षितिज", "Kshitij"), Pair("यज्ञेश", "Yadnyesh"), Pair("ओजस", "Ojas"),
    Pair("चैतन्य", "Chaitanya"), Pair("अद्वैत", "Advait"), Pair("सौरभ", "Saurabh"),
]
RARE_FEMALE_NAMES = [
    Pair("ज्ञानदा", "Dnyanada"), Pair("ऐश्वर्या", "Aishwarya"), Pair("तृप्ती", "Trupti"),
    Pair("ज्योत्स्ना", "Jyotsna"), Pair("मृणाल", "Mrunal"), Pair("श्वेता", "Shweta"),
    Pair("ऋचा", "Rucha"), Pair("स्मिता", "Smita"),
]
RARE_SURNAMES = [
    Pair("ढमढेरे", "Dhamdhere"), Pair("क्षीरसागर", "Kshirsagar"), Pair("घोडके", "Ghodke"),
    Pair("वाघमारे", "Waghmare"), Pair("ठोंबरे", "Thombre"), Pair("झोडगे", "Zodge"),
    Pair("बोऱ्हाडे", "Borhade"),
]

RARE_VARIANTS: dict[str, Pair] = {
    "Rugved": Pair("ऋग्वेद", "Rugwed"), "Hrishikesh": Pair("ऋषिकेश", "Rushikesh"),
    "Shrinivas": Pair("श्रीनिवास", "Shreenivas"), "Yadnyesh": Pair("यज्ञेश", "Yagnesh"),
    "Dnyanada": Pair("ज्ञानदा", "Gyanada"), "Trupti": Pair("तृप्ति", "Trupti"),
    "Mrunal": Pair("मृणाल", "Mrinal"), "Jyotsna": Pair("ज्योत्सना", "Jyotsana"),
    "Kshirsagar": Pair("क्षिरसागर", "Ksheersagar"), "Waghmare": Pair("वाघमारे", "Vaghmare"),
    "Thombre": Pair("ठोंबरे", "Thombare"), "Dhamdhere": Pair("ढमढेरे", "Dhamdhare"),
}

ALL_MALE = MALE_NAMES + RARE_MALE_NAMES
ALL_FEMALE = FEMALE_NAMES + RARE_FEMALE_NAMES
ALL_SURNAMES = SURNAMES + RARE_SURNAMES
ALL_VARIANTS = {**VARIANTS, **RARE_VARIANTS}

RELATIONS_EXTRA = {"father": Pair("वडील", "Father")}

# For synthetic data only. Verify against official sources before rules depend on them.
NEO_BUDDHIST = Pair("नवबौद्ध", "Neo-Buddhist")
CASTE_CATEGORIES_V2 = CASTE_CATEGORIES + [NEO_BUDDHIST]

# Ration card colour -> card type. For synthetic data only. Verify against official sources.
CARD_COLOURS: dict[str, dict[str, Pair]] = {
    "yellow": {"colour": Pair("पिवळी", "Yellow"), "category": Pair("अंत्योदय अन्न योजना (AAY)", "Antyodaya Anna Yojana (AAY)")},
    "orange": {"colour": Pair("केशरी", "Orange"), "category": Pair("प्राधान्य कुटुंब (PHH)", "Priority Household (PHH)")},
    "white": {"colour": Pair("पांढरी", "White"), "category": Pair("अप्राधान्य कुटुंब (NPHH)", "Non-Priority Household (NPHH)")},
}
