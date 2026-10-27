"""Hand-written Marathi name and label lists for synthetic SPECIMEN documents.

Every entry is a (Devanagari, English) pair. English spellings follow common usage; they
are not produced by a transliteration library, so they look like what people actually write.
"""

from typing import NamedTuple


class Pair(NamedTuple):
    mr: str
    en: str


MALE_NAMES = [
    Pair("सुनील", "Sunil"), Pair("रमेश", "Ramesh"), Pair("संतोष", "Santosh"),
    Pair("गणेश", "Ganesh"), Pair("प्रकाश", "Prakash"), Pair("विजय", "Vijay"),
    Pair("अनिल", "Anil"), Pair("महेश", "Mahesh"), Pair("दत्तात्रय", "Dattatray"),
    Pair("बाळासाहेब", "Balasaheb"), Pair("नामदेव", "Namdev"), Pair("ज्ञानेश्वर", "Dnyaneshwar"),
    Pair("तुकाराम", "Tukaram"), Pair("शंकर", "Shankar"), Pair("राहुल", "Rahul"),
    Pair("अमोल", "Amol"), Pair("सचिन", "Sachin"), Pair("विठ्ठल", "Vitthal"),
    Pair("किरण", "Kiran"), Pair("योगेश", "Yogesh"), Pair("ओंकार", "Omkar"),
    Pair("आदित्य", "Aditya"), Pair("साईराज", "Sairaj"), Pair("पांडुरंग", "Pandurang"),
]

FEMALE_NAMES = [
    Pair("सुनीता", "Sunita"), Pair("मनीषा", "Manisha"), Pair("संगीता", "Sangita"),
    Pair("सविता", "Savita"), Pair("अनिता", "Anita"), Pair("वैशाली", "Vaishali"),
    Pair("रेखा", "Rekha"), Pair("लता", "Lata"), Pair("मीरा", "Meera"),
    Pair("कविता", "Kavita"), Pair("प्रियांका", "Priyanka"), Pair("स्नेहा", "Sneha"),
    Pair("पूजा", "Pooja"), Pair("अश्विनी", "Ashwini"), Pair("सुवर्णा", "Suvarna"),
    Pair("शारदा", "Sharada"), Pair("रुक्मिणी", "Rukmini"), Pair("गौरी", "Gauri"),
    Pair("सायली", "Sayali"), Pair("ऋतुजा", "Rutuja"), Pair("कमल", "Kamal"),
    Pair("जयश्री", "Jayashree"),
]

SURNAMES = [
    Pair("पाटील", "Patil"), Pair("जाधव", "Jadhav"), Pair("पवार", "Pawar"),
    Pair("शिंदे", "Shinde"), Pair("कदम", "Kadam"), Pair("गायकवाड", "Gaikwad"),
    Pair("चव्हाण", "Chavan"), Pair("देशमुख", "Deshmukh"), Pair("कुलकर्णी", "Kulkarni"),
    Pair("भोसले", "Bhosale"), Pair("मोरे", "More"), Pair("साळुंखे", "Salunkhe"),
    Pair("खरात", "Kharat"), Pair("काळे", "Kale"), Pair("सावंत", "Sawant"),
    Pair("माने", "Mane"),
]

# Realistic alternate spellings, keyed by the canonical English spelling. Used to plant
# name mismatches; at least one script differs from the canonical pair.
VARIANTS: dict[str, Pair] = {
    # given names
    "Sunil": Pair("सुनिल", "Suneel"), "Anil": Pair("अनील", "Aneel"),
    "Rahul": Pair("राहूल", "Rahool"), "Omkar": Pair("ओमकार", "Onkar"),
    "Dattatray": Pair("दत्तात्रेय", "Dattatreya"), "Dnyaneshwar": Pair("ज्ञानेश्वर", "Gyaneshwar"),
    "Vitthal": Pair("विठ्ठल", "Vithal"), "Namdev": Pair("नामदेव", "Namadev"),
    "Balasaheb": Pair("बालासाहेब", "Balasaheb"), "Sairaj": Pair("साइराज", "Sairaj"),
    "Pandurang": Pair("पांडूरंग", "Pandurang"),
    "Sunita": Pair("सुनिता", "Suneeta"), "Manisha": Pair("मनिषा", "Maneesha"),
    "Sangita": Pair("संगिता", "Sangeeta"), "Anita": Pair("अनीता", "Aneeta"),
    "Savita": Pair("सविता", "Savitha"), "Kavita": Pair("कविता", "Kavitha"),
    "Lata": Pair("लता", "Latha"), "Pooja": Pair("पुजा", "Puja"),
    "Ashwini": Pair("अश्विनि", "Aswini"), "Jayashree": Pair("जयश्री", "Jayshri"),
    "Priyanka": Pair("प्रियंका", "Priyanka"), "Rutuja": Pair("रुतुजा", "Rutuja"),
    "Suvarna": Pair("सुवर्णा", "Suwarna"), "Sharada": Pair("शारदा", "Sharda"),
    "Rukmini": Pair("रुक्मीणी", "Rukmini"), "Gauri": Pair("गौरी", "Gowri"),
    "Vaishali": Pair("वैशालि", "Vaishali"), "Meera": Pair("मीरा", "Mira"),
    # surnames
    "Patil": Pair("पाटिल", "Paatil"), "Jadhav": Pair("जाधव", "Jadhao"),
    "Pawar": Pair("पवार", "Powar"), "Gaikwad": Pair("गायकवाड", "Gaekwad"),
    "Chavan": Pair("चव्हान", "Chavhan"), "Kulkarni": Pair("कुलकर्णि", "Kulkarni"),
    "Bhosale": Pair("भोसले", "Bhonsle"), "Salunkhe": Pair("साळुंके", "Salunke"),
    "Sawant": Pair("सावंत", "Savant"),
}

RELATIONS = {
    "self": Pair("स्वतः", "Self"),
    "wife": Pair("पत्नी", "Wife"),
    "son": Pair("मुलगा", "Son"),
    "daughter": Pair("मुलगी", "Daughter"),
    "mother": Pair("आई", "Mother"),
    "mother_in_law": Pair("सासू", "Mother-in-law"),
}

GENDERS = {"M": Pair("पुरुष", "Male"), "F": Pair("स्त्री", "Female")}

# Clearly fictional places ("namuna" = sample, "kalpit" = imaginary).
VILLAGES = [
    Pair("नमुनापूर", "Namunapur"), Pair("कल्पितवाडी", "Kalpitwadi"),
    Pair("उदाहरणगाव", "Udaharangaon"), Pair("चाचणीनगर", "Chachaninagar"),
]
TALUKA = Pair("नमुना", "Namuna")
DISTRICT = Pair("कल्पित", "Kalpit")
OFFICE = Pair("तहसीलदार कार्यालय, नमुना तालुका", "Tahsildar Office, Namuna Taluka")

# For synthetic data only. Verify against official sources before rules depend on them.
RATION_CARD_CATEGORIES = [
    Pair("अंत्योदय अन्न योजना (AAY)", "Antyodaya Anna Yojana (AAY)"),
    Pair("प्राधान्य कुटुंब (PHH)", "Priority Household (PHH)"),
    Pair("अप्राधान्य कुटुंब (NPHH)", "Non-Priority Household (NPHH)"),
]
CASTE_CATEGORIES = [
    Pair("अनुसूचित जाती (SC)", "Scheduled Caste (SC)"),
    Pair("अनुसूचित जमाती (ST)", "Scheduled Tribe (ST)"),
    Pair("इतर मागास वर्ग (OBC)", "Other Backward Class (OBC)"),
    Pair("विमुक्त जाती व भटक्या जमाती (VJNT)", "Vimukta Jati and Nomadic Tribes (VJNT)"),
]
