"""Scheme catalog (GET /schemes): every scheme and rule from the YAML, values as written there, wording in
en/hi/mr, statuses and sources passed through, conflicts listing every reported source."""

import re

import pytest

from agents.catalog import catalog
from app.api.routes import schemes
from rules.loader import load_schemes


@pytest.mark.parametrize("language", ["en", "hi", "mr"])
def test_every_scheme_and_rule_is_listed(language: str) -> None:
    cards = {c.id: c for c in catalog(language)}
    assert set(cards) == {s.id for s in load_schemes()}
    for scheme in load_schemes():
        card = cards[scheme.id]
        assert [line.rule_id for line in card.rules] == [r.id for r in scheme.rules]
        assert [line.rule_id for line in card.other_proof] == [p.id for p in scheme.needs_other_proof]
        for line, rule in zip(card.rules, scheme.rules):
            assert line.status == rule.status and line.sources and line.text
            if rule.status != "conflict":
                assert [(s.source, s.url) for s in line.sources] == [(rule.source, rule.source_url)]


def test_values_come_from_the_yaml_in_english() -> None:
    ladki = next(c for c in catalog("en") if c.id == "ladki_bahin")
    texts = [line.text for line in ladki.rules]
    assert texts[:4] == ["For women.", "Age 21 or more.", "Age 65 or less.", "Family income up to ₹2,50,000."]
    assert texts[4] == "An income certificate, or a yellow or orange ration card."
    ujjwala = next(c for c in catalog("en") if c.id == "pm_ujjwala")
    assert "Documents: ration card, Aadhaar card of every adult on the ration card." in [x.text for x in ujjwala.rules]


def test_conflicting_values_list_every_source() -> None:
    ramai = next(c for c in catalog("en") if c.id == "ramai_awas")
    bands = next(line for line in ramai.rules if line.check == "income_bands")
    assert bands.status == "conflict" and len(bands.sources) >= 2
    assert bands.text == "Family income up to ₹1,00,000; sources differ between ₹1,00,000 and ₹1,50,000."


@pytest.mark.parametrize("language", ["hi", "mr"])
def test_rule_lines_have_no_english(language: str) -> None:
    for card in catalog(language):
        for line in card.rules:
            assert not re.search(r"[A-Za-z]{3,}", line.text.replace("SC", "").replace("ST", "").replace("NB", "")), line


@pytest.mark.parametrize("language", ["en", "hi", "mr"])
def test_names_short_names_and_benefits_in_every_language(language: str) -> None:
    for card in catalog(language):
        assert card.name and card.short and card.benefit.text and card.benefit.sources
        if language != "en":
            assert not re.search(r"[A-Za-z]", card.name + card.short), card.id
    ladki = {c.id: c for c in catalog("mr")}["ladki_bahin"]
    assert ladki.name == "मुख्यमंत्री माझी लाडकी बहीण योजना" and ladki.short == "लाडकी बहीण"
    assert ladki.benefit.status == "verified" and ladki.benefit.sources[0].url == "https://myscheme.gov.in/schemes/mmlby"
    shravanbal = {c.id: c for c in catalog("hi")}["shravanbal"]
    assert shravanbal.short == "श्रावणबाल" and shravanbal.benefit.status == "unverified"
    assert shravanbal.benefit.sources[0].source == "developer"


def test_route_returns_plain_json() -> None:
    out = schemes("mr")
    assert len(out) == 5 and out[0]["rules"][0]["sources"][0]["source"]
