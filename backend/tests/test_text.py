import unicodedata

from vision.text import normalize_text

VISARGA = "ः"


def test_trailing_colon_becomes_visarga() -> None:
    assert normalize_text("स्वत:") == "स्वतः"
    assert normalize_text("स्वत:").endswith(VISARGA)


def test_mid_word_colon_becomes_visarga() -> None:
    assert normalize_text("दु:ख") == "दुःख"


def test_label_colon_followed_by_space_is_kept() -> None:
    assert normalize_text("नाव: सुनील") == "नाव: सुनील"


def test_colon_after_latin_or_digit_is_kept() -> None:
    assert normalize_text("Name:") == "Name:"
    assert normalize_text("10:30") == "10:30"


def test_existing_visarga_unchanged() -> None:
    assert normalize_text("स्वतः") == "स्वतः"


def test_nfc_applied() -> None:
    decomposed = unicodedata.normalize("NFD", "क़")  # क + nukta
    assert normalize_text(decomposed) == unicodedata.normalize("NFC", "क़")
