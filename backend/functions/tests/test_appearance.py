import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb  # noqa: E402
from petlogic.appearance import all_keys, appearance_of  # noqa: E402
from petlogic.pet import get_pet  # noqa: E402
from petlogic.register import register_device  # noqa: E402

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)
AXES = {"activity": 0.5, "friendly": 0.5, "talkative": 0.5, "logical": 0.5, "curious": 0.5, "nightowl": 0.5}


def test_top_two_axes_decide_the_key():
    axes = {**AXES, "nightowl": 0.7, "curious": 0.6}
    a = appearance_of("p1", axes, "baby")
    assert a == {"stage": "baby", "primary": "nightowl", "secondary": "curious",
                 "key": "nightowl_curious_baby", "fallbackKey": "nightowl_baby"}
    assert appearance_of("p1", axes, "adult")["key"] == "nightowl_curious_adult"


def test_changes_when_personality_changes():
    before = appearance_of("p1", {**AXES, "nightowl": 0.7, "curious": 0.6}, "child")["key"]
    after = appearance_of("p1", {**AXES, "nightowl": 0.6, "curious": 0.7}, "child")["key"]
    assert before == "nightowl_curious_child" and after == "curious_nightowl_child"


def test_ties_are_stable_per_pet_and_vary_between_pets():
    results = {appearance_of(f"pet{i}", AXES, "baby")["key"] for i in range(30)}
    assert len(results) > 3  # 生まれたては、ペットごとに、ばらける
    assert appearance_of("same", AXES, "baby") == appearance_of("same", AXES, "baby")
    a = appearance_of("same", AXES, "baby")
    assert a["primary"] != a["secondary"]


def test_missing_axes_and_all_keys():
    assert appearance_of("p", None, "baby")["key"].endswith("_baby")
    keys = all_keys()
    assert len(keys) == 108 and len(set(keys)) == 108  # (6 + 6×5) × 3段階
    assert "nightowl_curious_baby" in keys and "nightowl_baby" in keys


def test_get_pet_returns_appearance():
    db = FakeDb()
    pet = register_device(db, "u1", "devA", NOW)["petId"]
    db.docs[("pets", pet)]["personalityAxes"].update({"logical": 0.9, "talkative": 0.8})
    info = get_pet(db, "u1", "devA")
    assert info["appearance"]["key"] == "logical_talkative_baby" and info["appearance"]["stage"] == "baby"
