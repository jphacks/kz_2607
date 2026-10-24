import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.exchange import cancel_exchange, get_exchange_result, report_exchange  # noqa: E402
from petlogic.register import register_device  # noqa: E402

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def setup():
    """u1 の端末A(ペットPA)と、u2 の端末B(ペットPB)を用意する。"""
    db = FakeDb()
    a = register_device(db, "u1", "devA", NOW)["petId"]
    b = register_device(db, "u2", "devB", NOW)["petId"]
    return db, a, b


def report(db, uid, me, peer, given, got, tid="t1", **extra):
    data = {"myDeviceId": me, "peerDeviceId": peer, "givenPetId": given, "gotPetId": got,
            "transactionId": tid, **extra}
    return report_exchange(db, uid, data, NOW, run_tx=run_tx)


def cancel(db, uid, me, peer, tid="t1"):
    return cancel_exchange(db, uid, {"transactionId": tid, "myDeviceId": me, "peerDeviceId": peer},
                           NOW, run_tx=run_tx)


def result(db, uid, me, tid="t1"):
    return get_exchange_result(db, uid, {"transactionId": tid, "myDeviceId": me})


def err(fn, *args, **kw):
    with pytest.raises(ApiError) as e:
        fn(*args, **kw)
    return e.value


def test_exchange_swaps_pets_and_bumps_generation():
    db, a, b = setup()
    r = report(db, "u1", "devA", "devB", a, b, location="shibuya", rssi=-60)
    assert r["status"] == "done" and r["replayed"] is False
    assert r["receivedPetId"] == b and r["givenPetId"] == a and r["receivedPetGeneration"] == 2
    assert db.docs[("devices", "devA")]["currentPetId"] == b
    assert db.docs[("devices", "devB")]["currentPetId"] == a
    assert db.docs[("pets", a)]["generation"] == 2 and db.docs[("pets", b)]["generation"] == 2
    assert db.docs[("handoffs", r["handoffId"])]["location"] == "shibuya"
    assert db.docs[("devices", "devA")]["lastHandoffId"] == r["handoffId"]


def test_resend_same_device_is_replayed_done():
    db, a, b = setup()
    first = report(db, "u1", "devA", "devB", a, b)
    again = report(db, "u1", "devA", "devB", a, b)
    assert again["status"] == "done" and again["replayed"] is True
    assert again["handoffId"] == first["handoffId"]
    assert db.docs[("pets", a)]["generation"] == 2  # 二重に増えない


def test_other_device_report_is_already_done_from_its_view():
    db, a, b = setup()
    first = report(db, "u1", "devA", "devB", a, b)
    second = report(db, "u2", "devB", "devA", b, a)
    assert second["status"] == "already_done"
    assert second["receivedPetId"] == a and second["givenPetId"] == b
    assert second["handoffId"] == first["handoffId"]


def test_transaction_id_reused_for_different_content():
    db, a, b = setup()
    c = register_device(db, "u3", "devC", NOW)["petId"]
    report(db, "u1", "devA", "devB", a, b)
    assert err(report, db, "u3", "devC", "devA", c, a).reason == "transaction_mismatch"
    assert err(report, db, "u2", "devB", "devA", b, c).reason == "transaction_mismatch"


def test_state_mismatch_writes_nothing():
    db, a, b = setup()
    c = register_device(db, "u3", "devC", NOW)["petId"]
    before = {k: dict(v) for k, v in db.docs.items()}
    e = err(report, db, "u1", "devA", "devB", c, b, tid="t9")  # 自分のペットではない
    assert e.code == "failed-precondition" and e.reason is None
    assert db.docs == before


def test_cancel_then_report_is_rejected():
    db, a, b = setup()
    assert cancel(db, "u1", "devA", "devB")["status"] == "cancelled"
    assert cancel(db, "u1", "devA", "devB")["status"] == "cancelled"
    assert err(report, db, "u2", "devB", "devA", b, a).reason == "exchange_cancelled"
    assert db.docs[("devices", "devA")]["currentPetId"] == a


def test_cancel_after_confirmed_returns_confirmed():
    db, a, b = setup()
    report(db, "u1", "devA", "devB", a, b)
    r = cancel(db, "u2", "devB", "devA")
    assert r["status"] == "confirmed" and r["receivedPetId"] == a and r["currentPetId"] == a


def test_get_result_unknown_confirmed_cancelled():
    db, a, b = setup()
    assert result(db, "u1", "devA") == {"status": "unknown", "transactionId": "t1"}
    report(db, "u1", "devA", "devB", a, b)
    ra, rb = result(db, "u1", "devA"), result(db, "u2", "devB")
    assert ra["status"] == "confirmed" and ra["receivedPetId"] == b and ra["currentPetId"] == b
    assert rb["receivedPetId"] == a and rb["givenPetId"] == b
    cancel(db, "u1", "devA", "devB", tid="t2")
    assert result(db, "u1", "devA", tid="t2")["status"] == "cancelled"


def test_get_result_for_non_party_is_mismatch():
    db, a, b = setup()
    register_device(db, "u3", "devC", NOW)
    report(db, "u1", "devA", "devB", a, b)
    assert err(result, db, "u3", "devC").reason == "transaction_mismatch"


def test_not_own_device_is_denied():
    db, a, b = setup()
    assert err(report, db, "u2", "devA", "devB", a, b).code == "permission-denied"
    assert err(result, db, "u2", "devA").code == "permission-denied"
    assert err(cancel, db, "u2", "devA", "devB").code == "permission-denied"


def test_unregistered_peer_and_pets_are_not_found():
    db, a, b = setup()
    assert err(report, db, "u1", "devA", "ghost", a, b).code == "not-found"
    assert err(result, db, "u1", "ghost").code == "not-found"


@pytest.mark.parametrize(
    "patch",
    [
        {"transactionId": None},
        {"transactionId": "a b"},
        {"peerDeviceId": "devA"},        # 自分自身
        {"gotPetId": "SAME"},            # 同じペット
        {"myDeviceId": ""},
        {"givenPetId": 5},
    ],
)
def test_invalid_arguments(patch):
    db, a, b = setup()
    data = {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a, "gotPetId": b,
            "transactionId": "t1"}
    data.update({k: (a if v == "SAME" else v) for k, v in patch.items()})
    e = err(report_exchange, db, "u1", data, NOW, run_tx=run_tx)
    assert e.code == "invalid-argument"
