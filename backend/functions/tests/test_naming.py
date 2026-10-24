import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.naming import clean_name, set_pet_name  # noqa: E402
from petlogic.pet import get_pet  # noqa: E402
from petlogic.register import register_device  # noqa: E402
from petlogic.talk import build_ai_payload  # noqa: E402

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


def setup():
    db = FakeDb()
    a = register_device(db, "u1", "devA", NOW)["petId"]
    b = register_device(db, "u2", "devB", NOW)["petId"]
    return db, a, b


def name(db, uid, dev, value):
    return set_pet_name(db, uid, {"deviceId": dev, "name": value}, run_tx)


def err(fn):
    with pytest.raises(ApiError) as e:
        fn()
    return e.value


def test_name_is_set_once_and_shown_everywhere():
    db, a, _ = setup()
    r = name(db, "u1", "devA", "  モチ ")
    assert r == {"status": "ok", "petId": a, "name": "モチ", "firstPerson": None, "firstWords": None,
                 "birthStatus": "born", "alreadySet": False, "alreadyBorn": False}
    assert get_pet(db, "u1", "devA")["name"] == "モチ"
    assert build_ai_payload("x", a, db.docs[("pets", a)], NOW)["petName"] == "モチ"


def test_same_name_again_is_ok_but_a_different_name_is_refused():
    db, a, _ = setup()
    name(db, "u1", "devA", "モチ")
    assert name(db, "u1", "devA", "モチ")["alreadySet"] is True
    e = err(lambda: name(db, "u1", "devA", "ムギ"))
    assert e.code == "failed-precondition" and e.reason == "name_already_set" and e.extra["name"] == "モチ"
    assert db.docs[("pets", a)]["name"] == "モチ"


def test_only_the_creator_can_name_and_only_with_own_device():
    db, a, b = setup()
    assert err(lambda: name(db, "u2", "devA", "モチ")).code == "permission-denied"  # 人の端末
    report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                               "gotPetId": b, "transactionId": "t1"}, NOW, run_tx=run_tx)
    e = err(lambda: name(db, "u1", "devA", "モチ"))  # u1 は、今は u2 が作ったペットを持っている
    assert e.code == "permission-denied" and e.reason == "not_creator"
    assert db.docs[("pets", b)].get("name") is None
    assert err(lambda: name(db, "u1", "nope", "モチ")).code == "not-found"


def test_name_survives_exchange():
    db, a, b = setup()
    name(db, "u1", "devA", "モチ")
    report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                               "gotPetId": b, "transactionId": "t1"}, NOW, run_tx=run_tx)
    assert get_pet(db, "u2", "devB")["name"] == "モチ"
    e = err(lambda: name(db, "u2", "devB", "ムギ"))  # 新しい飼い主も、変えられない
    assert e.code == "permission-denied"


def test_name_validation():
    for bad in (None, 5, "", "   ", "あ" * 13, "モ\nチ", "http://x", "<b>", "命令を無視して", "ignore this", "09012345678"):
        assert err(lambda bad=bad: clean_name(bad)).code == "invalid-argument"
    assert clean_name("あ" * 12) == "あ" * 12 and clean_name("Mochi") == "Mochi"
