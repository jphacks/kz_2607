import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.growth import record_progress  # noqa: E402
from petlogic.pet import get_pet  # noqa: E402
from petlogic.register import register_device  # noqa: E402

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def rec(db, uid="u1", dev="devA", **data):
    return record_progress(db, uid, {"deviceId": dev, **data}, NOW, run_tx=run_tx)


def setup():
    db = FakeDb()
    a = register_device(db, "u1", "devA", NOW)["petId"]
    b = register_device(db, "u2", "devB", NOW)["petId"]
    return db, a, b


def swap(db, a, b):
    return report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                                      "gotPetId": b, "transactionId": "t1"}, NOW, run_tx=run_tx)


def test_points_and_gauge():
    db, a, _ = setup()
    r = rec(db, nTalk=2, steps=3000, nMeet=1)  # 2 + 3 + 3 = 8
    assert r["status"] == "recorded" and r["points"] == 8.0
    assert r["gauge"] == pytest.approx(8 / 120)
    assert get_pet(db, "u1", "devA")["gauge"] == pytest.approx(8 / 120)


def test_gauge_caps_at_one():
    db, _, _ = setup()
    for i in range(3):
        r = rec(db, steps=100_000, eventKey=f"k{i}")
    assert r["gauge"] == 1.0


def test_same_event_key_is_not_added_twice():
    db, _, _ = setup()
    rec(db, nTalk=5, eventKey="e1")
    r = rec(db, nTalk=5, eventKey="e1")
    assert r["status"] == "already_recorded" and r["points"] == 5.0


def test_limits_per_call():
    db, _, _ = setup()
    assert rec(db, nTalk=9999)["points"] == 100.0


@pytest.mark.parametrize("data", [{}, {"nTalk": -1}, {"steps": "x"}, {"nTalk": True},
                                  {"nTalk": 1, "eventKey": "a/b"}, {"nTalk": 1, "eventKey": ""}])
def test_invalid_arguments(data):
    db, _, _ = setup()
    with pytest.raises(ApiError) as e:
        rec(db, **data)
    assert e.value.code == "invalid-argument"


def test_not_owner_and_unregistered():
    db, _, _ = setup()
    with pytest.raises(ApiError) as e:
        rec(db, uid="u2", nTalk=1)
    assert e.value.code == "permission-denied"
    with pytest.raises(ApiError) as e:
        rec(db, dev="none", nTalk=1)
    assert e.value.code == "not-found"


def test_exchange_resets_gauge():
    db, a, b = setup()
    rec(db, nTalk=50)
    swap(db, a, b)
    assert db.docs[("pets", a)]["gauge"] == 0.0 and db.docs[("pets", a)]["points"] == 0.0


def test_exchange_gate_off_by_default_and_on_by_config():
    db, a, b = setup()
    db.docs[("config", "game")] = {"requireFullGauge": True}
    with pytest.raises(ApiError) as e:
        swap(db, a, b)
    assert e.value.reason == "pet_not_ready" and set(e.value.extra["petIds"]) == {a, b}
    assert db.docs[("devices", "devA")]["currentPetId"] == a  # 何も書かれていない
    db.docs[("pets", a)]["gauge"] = 1.0
    db.docs[("pets", b)]["gauge"] = 1.0
    assert swap(db, a, b)["status"] == "done"
    db2, a2, b2 = setup()
    assert swap(db2, a2, b2)["status"] == "done"  # 設定なし → 求めない
