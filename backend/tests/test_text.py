import unicodedata

import pytest

from vision.text import mask_identity_number, normalize_text, redact_identity_numbers

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


@pytest.mark.parametrize("raw", ["012345678901", "0123 4567 8901", "0123-4567-8901", "8901", "XXXX 8901"])
def test_mask_identity_number(raw: str) -> None:
    assert mask_identity_number(raw) == "XXXX XXXX 8901"


def test_mask_identity_number_devanagari_digits() -> None:
    assert mask_identity_number("०१२३ ४५६७ ८९०१") == "XXXX XXXX 8901"


def test_mask_identity_number_rejects_non_numbers() -> None:
    with pytest.raises(ValueError):
        mask_identity_number("unknown")


@pytest.mark.parametrize(
    "raw",
    [
        '{"id_number": "012345678901"}',
        '{"id_number": "0123 4567 8901"}',
        '{"id_number": "0123-4567-8901"}',
        '{"id_number": "०१२३ ४५६७ ८९०१"}',
    ],
)
def test_redact_catches_plain_spaced_dashed_and_devanagari(raw: str) -> None:
    out = redact_identity_numbers(raw)
    assert out == '{"id_number": "XXXX XXXX 8901"}'
    assert "0123" not in out and "4567" not in out


def test_redact_in_free_text_and_multiple() -> None:
    text = "IDs 1111 2222 3333 and 0123-4567-8901 seen"
    assert redact_identity_numbers(text) == "IDs XXXX XXXX 3333 and XXXX XXXX 8901 seen"


def test_redact_leaves_other_numbers_alone() -> None:
    for text in ["SPEC-RC-41010761", "SPEC/INC/768290", "Rs. 1,20,000", "27/02/2022", "9876543210"]:
        assert redact_identity_numbers(text) == text
    # part of a longer digit run: not an identity number
    assert redact_identity_numbers("1234567890123") == "1234567890123"
