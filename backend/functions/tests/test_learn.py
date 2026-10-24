import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.learn import clean_words, learn_words  # noqa: E402
from petlogic.register import register_device  # noqa: E402

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def test_clean_keeps_ordinary_words_max_three():
    assert clean_words(["みかん", "ねこ", "さんぽ", "あめ"]) == ["みかん", "ねこ", "さんぽ"]


def test_clean_drops_duplicates_empty_and_non_strings():
    assert clean_words(["みかん", "みかん", " ", "", 5, None, " ねこ "]) == ["みかん", "ねこ"]


@pytest.mark.parametrize(
    "bad",
    [
        "あ" * 21,
        "http://example.com",
        "ＨＴＴＰ：／／ｘ",          # 全角のURL
        "foo@example.com",
        "090-1234-5678",
        "12345",
        "前の指示を無視して",
        "ignore previous",
        "System prompt",
        "改行\nあり",
        "<script>",
    ],
)
def test_clean_blocks_unsafe_words(bad):
    assert clean_words([bad]) == []


def test_clean_non_list():
    assert clean_words("みかん") == [] and clean_words(None) == []


def setup():
    db = FakeDb()
    pet = register_device(db, "u1", "devA", NOW)["petId"]
    return db, pet


def learn(db, pet, words, uid="u1"):
    return learn_words(db, uid, "devA", pet, words, NOW, run_tx=run_tx)


def test_learn_adds_new_words_only():
    db, pet = setup()
    assert learn(db, pet, ["みかん"]) == ["みかん"]
    assert learn(db, pet, ["みかん", "ねこ"]) == ["ねこ"]
    assert db.docs[("pets", pet)]["learnedWords"] == ["みかん", "ねこ"]


def test_learn_stops_at_50_words():
    db, pet = setup()
    db.docs[("pets", pet)]["learnedWords"] = [f"w{i}" for i in range(49)]
    assert learn(db, pet, ["あ", "い", "う"]) == ["あ"]
    assert len(db.docs[("pets", pet)]["learnedWords"]) == 50
    assert learn(db, pet, ["え"]) == []


def test_learn_only_for_current_owner_and_pet():
    db, pet = setup()
    assert learn(db, pet, ["みかん"], uid="u2") == []
    assert learn(db, "other-pet", ["みかん"]) == []
    assert db.docs[("pets", pet)]["learnedWords"] == []
