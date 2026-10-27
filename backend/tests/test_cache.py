from clients.cache import DiskCache, make_key

BASE = {
    "provider": "baseten",
    "model": "m",
    "system": "sys",
    "prompt": "p",
    "image": b"\xff\xd8jpeg",
    "temperature": 0.0,
    "max_tokens": 100,
    "response_format": {"type": "json_object"},
}


def test_key_is_stable_and_order_independent() -> None:
    reordered = dict(reversed(list(BASE.items())))
    assert make_key(BASE) == make_key(reordered)


def test_every_field_changes_the_key() -> None:
    changes = {
        "provider": "meta",
        "model": "other",
        "system": "sys2",
        "prompt": "p2",
        "image": b"\xff\xd8other",
        "temperature": 0.5,
        "max_tokens": 200,
        "response_format": None,
    }
    base_key = make_key(BASE)
    for field, value in changes.items():
        assert make_key({**BASE, field: value}) != base_key, field


def test_roundtrip_and_miss(tmp_path) -> None:
    cache = DiskCache(tmp_path / "c")
    key = make_key(BASE)
    assert cache.get(key) is None
    cache.set(key, {"text": "नमस्कार", "n": 1})
    assert cache.get(key) == {"text": "नमस्कार", "n": 1}
    assert not list((tmp_path / "c").glob("*.tmp"))


def test_corrupt_entry_is_a_miss(tmp_path) -> None:
    cache = DiskCache(tmp_path)
    key = make_key(BASE)
    (tmp_path / f"{key}.json").write_text("{not json", encoding="utf-8")
    assert cache.get(key) is None
    assert not (tmp_path / f"{key}.json").exists()
