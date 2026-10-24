import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.birth import birth_trait, parse_answers, set_initial_personality  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.register import register_device  # noqa: E402

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


def setup():
    db = FakeDb()
    a = register_device(db, "u1", "devA", NOW)["petId"]
    b = register_device(db, "u2", "devB", NOW)["petId"]
    return db, a, b


def call(db, uid="u1", dev="devA", answers=(0, 1, 2, 3, 3, 0), version=1, **extra):
    return set_initial_personality(db, uid, {"deviceId": dev, "answers": list(answers),
                                             "questionnaireVersion": version, **extra}, NOW, run_tx)


def err(fn):
    with pytest.raises(ApiError) as e:
        fn()
    return e.value


def test_sets_axes_base_trait_and_appearance_on_server():
    db, a, _ = setup()
    r = call(db, axes={"activity": 0.99})  # アプリの値は使わない
    assert r["personalityAxes"] == {"activity": 0.2, "friendly": 0.4, "talkative": 0.6, "logical": 0.8,
                                    "curious": 0.8, "nightowl": 0.2}
    assert r["birthTrait"] == "logic"  # logical と curious が同じ値 → logical が先
    assert r["alreadySet"] is False and r["appearance"]["key"].endswith("_baby")
    pet = db.docs[("pets", a)]
    assert pet["axesBase"] == pet["personalityAxes"] == r["personalityAxes"]
    assert pet["birthAnswers"] == [0, 1, 2, 3, 3, 0] and pet["questionnaireVersion"] == 1


def test_trait_tie_order():
    assert birth_trait({n: 0.4 for n in ("activity", "friendly", "talkative", "logical", "curious", "nightowl")}) == "active"
    assert birth_trait({"activity": 0.2, "friendly": 0.2, "talkative": 0.2, "logical": 0.2, "curious": 0.2,
                        "nightowl": 0.8}) == "night"


def test_same_answers_again_is_ok_but_different_is_rejected():
    db, a, _ = setup()
    call(db)
    assert call(db)["alreadySet"] is True
    assert err(lambda: call(db, answers=(3, 3, 3, 3, 3, 3))).reason == "personality_already_set"
    assert err(lambda: call(db, version=2)).reason == "personality_already_set"
    assert db.docs[("pets", a)]["birthAnswers"] == [0, 1, 2, 3, 3, 0]


def test_validation():
    for bad in ([0, 1, 2], [0, 1, 2, 3, 3, 4], [0, 1, 2, 3, 3, -1], [0, 1, 2, 3, 3, 1.5], [True] * 6, "abc", None):
        assert err(lambda: parse_answers(bad)).code == "invalid-argument"
    assert parse_answers({"activity": 3, "friendly": 2, "talkative": 1, "logical": 0, "curious": 0, "nightowl": 1}) \
        == [3, 2, 1, 0, 0, 1]
    db, _, _ = setup()
    assert err(lambda: call(db, version=0)).code == "invalid-argument"
    assert err(lambda: call(db, version="1")).code == "invalid-argument"


def test_only_creator_who_still_owns_first_generation_before_talking():
    db, a, b = setup()
    assert err(lambda: call(db, uid="u2")).code == "permission-denied"  # 他人の端末
    db.docs[("pets", a)]["totalTalks"] = 1
    assert err(lambda: call(db)).code == "failed-precondition"  # もう話した
    db.docs[("pets", a)]["totalTalks"] = 0
    report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a, "gotPetId": b,
                               "transactionId": "t1"}, NOW, run_tx=run_tx)
    assert err(lambda: call(db, dev="devA")).reason == "not_creator"  # 交換のあと、手元にいるのは他人が作ったペット
    db.docs[("pets", a)].update({"ownerUid": "u2", "generation": 2})
    db.docs[("devices", "devA")]["currentPetId"] = a  # 作った本人の端末に戻っても、2代目以降は決められない
    assert err(lambda: call(db, dev="devA")).reason == "personality_not_allowed"
