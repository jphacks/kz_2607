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
    assert {k: a[k] for k in ("stage", "primary", "secondary", "key", "fallbackKey")} == {
        "stage": "baby", "primary": "nightowl", "secondary": "curious",
        "key": "nightowl_curious_baby", "fallbackKey": "nightowl_baby"}
    assert a["tertiary"] not in ("nightowl", "curious")  # 3番目は、残りの4軸のどれか
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


def test_tertiary_is_third_strongest_and_follows_fixed_order_on_ties():
    axes = {"activity": 0.8, "friendly": 0.6, "talkative": 0.4, "logical": 0.4, "curious": 0.2, "nightowl": 0.2}
    a = appearance_of("p1", axes, "baby", fixed_order=True)
    assert (a["primary"], a["secondary"], a["tertiary"]) == ("activity", "friendly", "talkative")  # 同点は決まった順
    assert len({a["primary"], a["secondary"], a["tertiary"]}) == 3


# ---- 種族(動物)は、誕生のときの軸で固定 ----
def test_species_is_fixed_but_eyes_and_mouth_follow_the_current_personality():
    axes = {**AXES, "curious": 0.8, "logical": 0.7, "nightowl": 0.6}  # いまの性格では、curious が一番強い
    a = appearance_of("p1", axes, "baby", species="nightowl")
    assert a["primary"] == "nightowl"  # 動物は固定
    assert (a["secondary"], a["tertiary"]) == ("curious", "logical")  # 目・口は、残りの中で強い順
    assert a["key"] == "nightowl_curious_baby" and a["fallbackKey"] == "nightowl_baby"
    assert len({a["primary"], a["secondary"], a["tertiary"]}) == 3


def test_species_stays_after_the_personality_moves_by_exchange():
    from petlogic.appearance import appearance_for_pet
    pet = {"personalityAxes": {**AXES, "nightowl": 0.8, "curious": 0.6}, "birthTrait": "night", "birthAnswers": [0] * 6}
    assert appearance_for_pet("p1", pet, "child")["primary"] == "nightowl"
    pet["personalityAxes"] = {**AXES, "nightowl": 0.6, "curious": 0.8}  # 交換のあと、性格が動いた
    a = appearance_for_pet("p1", pet, "child")
    assert a["primary"] == "nightowl" and a["secondary"] == "curious"


def test_old_pets_without_birth_trait_follow_the_current_personality():
    from petlogic.appearance import appearance_for_pet
    pet = {"personalityAxes": {**AXES, "curious": 0.8, "nightowl": 0.6}}
    assert appearance_for_pet("p1", pet, "baby")["primary"] == "curious"


def test_every_birth_trait_maps_to_an_axis_and_get_pet_uses_it():
    from petlogic.appearance import species_of
    from petlogic.talk import AI_AXIS_NAMES
    assert {species_of({"birthTrait": ai}) for ai in AI_AXIS_NAMES.values()} == set(AI_AXIS_NAMES)
    assert species_of({"birthTrait": "unknown"}) is None and species_of({}) is None
    db = FakeDb()
    pet = register_device(db, "u1", "devA", NOW)["petId"]
    db.docs[("pets", pet)].update({"personalityAxes": {**AXES, "curious": 0.9}, "birthTrait": "night"})
    assert get_pet(db, "u1", "devA")["appearance"]["primary"] == "nightowl"
