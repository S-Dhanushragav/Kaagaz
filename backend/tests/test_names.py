from matching.names import NamePair, devanagari_to_latin, name_score, simplify_latin


def test_transliteration_matches_common_english_spellings() -> None:
    assert devanagari_to_latin("सुनील रमेश पाटील") == "sunil ramesh patil"
    assert devanagari_to_latin("ज्ञानेश्वर") == simplify_latin("Dnyaneshwar")
    assert devanagari_to_latin("ऋग्वेद") == "rugved"
    assert devanagari_to_latin("बोऱ्हाडे") == "borhade"
    assert devanagari_to_latin("चव्हाण") == "chavhan"


def test_simplify_folds_spelling_variants() -> None:
    assert simplify_latin("Suneel") == simplify_latin("Sunil")
    assert simplify_latin("Vitthal") == simplify_latin("Vithal")
    assert simplify_latin("Waghmare") == simplify_latin("Vaghmare")


def test_same_person_scores_high_across_scripts_and_spellings() -> None:
    assert name_score(NamePair("सुनील रमेश पाटील", None), NamePair(None, "Sunil Ramesh Patil")) >= 90
    assert name_score(NamePair(None, "Suneel Ramesh Patil"), NamePair(None, "Sunil Ramesh Patil")) >= 90
    assert name_score(NamePair("सुनिल रमेश पाटील", None), NamePair("सुनील रमेश पाटील", None)) >= 90
    assert name_score(NamePair(None, "Rekha Omkar Jadhao"), NamePair(None, "Rekha Omkar Jadhav")) >= 90


def test_family_members_score_low() -> None:
    """Shared middle name and surname must not make siblings or spouses look like one person."""
    assert name_score(NamePair("ऋचा अद्वैत घोडके", "Rucha Advait Ghodke"),
                      NamePair("ओंकार अद्वैत घोडके", "Omkar Advait Ghodke")) < 70
    assert name_score(NamePair("स्मिता सुनील मोरे", "Smita Sunil More"),
                      NamePair("जयश्री सुनील मोरे", "Jayashree Sunil More")) < 70


def test_missing_names_score_zero() -> None:
    assert name_score(NamePair(None, None), NamePair(None, "Sunil")) == 0.0
