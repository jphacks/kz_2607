import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.growth import add_talk, gauge_of  # noqa: E402
from petlogic.pet import get_pet  # noqa: E402
from petlogic.register import register_device  # noqa: E402

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def setup():
    db = FakeDb()
    a = register_device(db, "u1", "devA", NOW)["petId"]
    b = register_device(db, "u2", "devB", NOW)["petId"]
    return db, a, b


def talk_once(db, a, uid="u1", dev="devA"):
    return add_talk(db, uid, dev, a, NOW, run_tx)


def swap(db, a, b):
    return report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                                      "gotPetId": b, "transactionId": "t1"}, NOW, run_tx=run_tx)


def test_ten_talks_fill_the_gauge():
    db, a, _ = setup()
    assert talk_once(db, a)["gauge"] == pytest.approx(1 / 10)
    assert talk_once(db, a)["gauge"] == pytest.approx(2 / 10)
    for _ in range(7):
        talk_once(db, a)
    assert talk_once(db, a)["gauge"] == 1.0
    assert talk_once(db, a)["gauge"] == 1.0  # 超えても1.0
    assert get_pet(db, "u1", "devA")["gauge"] == 1.0


def test_gauge_of_bounds():
    assert gauge_of(0) == 0 and gauge_of(99) == 1.0 and gauge_of(-5) == 0


def test_not_owner_or_changed_pet_is_ignored():
    db, a, b = setup()
    assert talk_once(db, a, uid="u2") is None
    assert add_talk(db, "u1", "devA", b, NOW, run_tx) is None  # 端末のペットではない
    assert add_talk(db, "u1", "none", a, NOW, run_tx) is None
    assert db.docs[("pets", a)]["points"] == 0.0


def test_failure_does_not_raise():
    class Boom(FakeDb):
        pass

    def bad_tx(db, fn):
        raise RuntimeError("down")

    db, a, _ = setup()
    assert add_talk(db, "u1", "devA", a, NOW, bad_tx) is None


def test_exchange_resets_gauge():
    db, a, b = setup()
    talk_once(db, a)
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


def test_exchange_records_new_owner_and_generation_start():
    db, a, b = setup()
    later = datetime(2026, 10, 25, tzinfo=timezone.utc)
    report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                               "gotPetId": b, "transactionId": "t9"}, later, run_tx=run_tx)
    assert db.docs[("pets", a)]["ownerUid"] == "u2" and db.docs[("pets", b)]["ownerUid"] == "u1"
    assert db.docs[("pets", a)]["creatorUid"] == "u1"  # 最初に作った人は変わらない
    assert db.docs[("pets", a)]["generationStartedAt"] == later


# ---- 姿の段階(赤ちゃん → 子供 → 大人) ----
from petlogic.growth import stage_config, stage_of  # noqa: E402


def test_stage_of_boundaries():
    assert stage_of(0, 30, 100) == {"stage": "baby", "stageIndex": 1, "nextStageAt": 30, "talksToNextStage": 30}
    assert stage_of(29, 30, 100)["stage"] == "baby"
    assert stage_of(30, 30, 100)["stage"] == "child" and stage_of(99, 30, 100)["stage"] == "child"
    assert stage_of(100, 30, 100) == {"stage": "adult", "stageIndex": 3, "nextStageAt": None, "talksToNextStage": None}
    assert stage_of(None, 30, 100)["stage"] == "baby"


def test_stage_config_defaults_and_overrides():
    db = FakeDb()
    assert stage_config(db) == (30, 100)
    db.docs[("config", "game")] = {"stageChildAt": 3, "stageAdultAt": 6.0}
    assert stage_config(db) == (3, 6)
    db.docs[("config", "game")] = {"stageChildAt": 9, "stageAdultAt": 5}  # 逆転は無効
    assert stage_config(db) == (30, 100)
    db.docs[("config", "game")] = {"stageChildAt": "x", "stageAdultAt": True}
    assert stage_config(db) == (30, 100)


def test_total_talks_survive_exchange_and_evolve_once():
    db, a, b = setup()
    db.docs[("config", "game")] = {"stageChildAt": 3, "stageAdultAt": 5}
    results = [talk_once(db, a) for _ in range(5)]
    assert [r["stage"] for r in results] == ["baby", "baby", "child", "child", "adult"]
    assert [r["evolved"] for r in results] == [False, False, True, False, True]
    swap(db, a, b)
    pet = db.docs[("pets", a)]
    assert pet["points"] == 0.0 and pet["totalTalks"] == 5  # ゲージは戻るが、累計は残る
    info = get_pet(db, "u2", "devB")
    assert info["totalTalks"] == 5 and info["stage"] == "adult" and info["stageIndex"] == 3


def test_get_pet_shows_stage_for_new_pet():
    db, a, _ = setup()
    info = get_pet(db, "u1", "devA")
    assert info["stage"] == "baby" and info["totalTalks"] == 0 and info["talksToNextStage"] == 30
