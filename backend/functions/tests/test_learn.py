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


def test_learn_replaces_oldest_words_at_50():
    db, pet = setup()
    db.docs[("pets", pet)]["learnedWords"] = [f"w{i}" for i in range(49)]
    assert learn(db, pet, ["あ", "い", "う"]) == ["あ", "い", "う"]  # 新しく覚えた言葉は、全部返す
    words = db.docs[("pets", pet)]["learnedWords"]
    assert len(words) == 50 and words[:2] == ["w2", "w3"] and words[-3:] == ["あ", "い", "う"]  # 古い2語(w0, w1)が消える
    assert learn(db, pet, ["え"]) == ["え"]
    assert db.docs[("pets", pet)]["learnedWords"][-1] == "え" and len(db.docs[("pets", pet)]["learnedWords"]) == 50
    assert "w2" not in db.docs[("pets", pet)]["learnedWords"]


def test_learn_at_50_does_not_change_when_word_already_known():
    db, pet = setup()
    db.docs[("pets", pet)]["learnedWords"] = [f"w{i}" for i in range(50)]
    assert learn(db, pet, ["w10"]) == []
    assert db.docs[("pets", pet)]["learnedWords"][0] == "w0"


def test_learn_at_50_still_records_history_for_journeys():
    db, pet = setup()
    db.docs[("pets", pet)]["learnedWords"] = [f"w{i}" for i in range(50)]
    learn(db, pet, ["あ"])
    hist = [v for k, v in db.docs.items() if k[0] == f"pets/{pet}/history"]
    assert any(h.get("words") == ["あ"] for h in hist)  # 上限に達しても、旅の記録のもとになる履歴は残る


def test_learn_only_for_current_owner_and_pet():
    db, pet = setup()
    assert learn(db, pet, ["みかん"], uid="u2") == []
    assert learn(db, "other-pet", ["みかん"]) == []
    assert db.docs[("pets", pet)]["learnedWords"] == []
