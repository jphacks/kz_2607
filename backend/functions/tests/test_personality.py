import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.growth import add_talk  # noqa: E402
from petlogic.personality import (maybe_update_personality, record_progress, sensor_levels,  # noqa: E402
                                  talk_levels, update_axes)
from petlogic.register import register_device  # noqa: E402
from petlogic.talklog import record_turn  # noqa: E402

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=JST)


def turn(text, hour=12, day=24):
    return {"text": text, "reply": "", "at": datetime(2026, 10, day, hour, tzinfo=JST)}


def setup():
    db = FakeDb()
    pet = register_device(db, "u1", "devA", NOW)["petId"]
    return db, pet


def talk(db, pet, text, hour=12, now=None):
    now = now or NOW.replace(hour=hour)
    record_turn(db, pet, 1, text, "うん", now, run_tx, uid="u1")
    add_talk(db, "u1", "devA", pet, now, run_tx)


# ---- 水準の計算 ----
def test_no_talks_no_levels():
    assert talk_levels([]) == {} and sensor_levels([]) == {}


def test_night_owl_and_confidence():
    levels = talk_levels([turn("a", 23), turn("b", 2), turn("c", 12), turn("d", 13)])
    assert levels["nightowl"] == (0.5, pytest.approx(0.4))


def test_logical_vs_sensual():
    logic = talk_levels([turn("だから理由はつまりこう")])["logical"][0]
    sense = talk_levels([turn("めっちゃすごい楽しい")])["logical"][0]
    assert logic > 0.5 > sense


def test_curious_questions_and_new_topics():
    many = talk_levels([turn("空はなぜ青いの？"), turn("明日の天気は何ですか"), turn("犬の名前を教えて")])["curious"][0]
    same = talk_levels([turn("おはよう"), turn("おはよう"), turn("おはよう")])["curious"][0]
    assert many > same


def test_sensor_levels_cap_and_confidence():
    levels = sensor_levels([{"steps": 24000, "meets": 10}, {"steps": 6000, "meets": 0}])
    assert levels["activity"] == (1.0, pytest.approx(2 / 3))
    assert levels["friendly"][0] == 1.0


def test_update_moves_toward_level_and_is_clamped():
    base = {"nightowl": 0.5}
    moved = update_axes({"nightowl": 0.5}, base, {"nightowl": (1.0, 1.0)}, 0.12, 0.2)
    assert moved["nightowl"] == pytest.approx(0.56)
    far = update_axes({"nightowl": 0.69}, base, {"nightowl": (1.0, 1.0)}, 0.5, 0.2)
    assert far["nightowl"] == 0.7  # 基準 ± 0.2 まで
    same = update_axes({"a": 0.3, "b": 0.4}, {}, {"a": (0.3, 1.0)}, 0.12, 0.2)
    assert same["b"] == 0.4  # 材料のない軸は動かない


# ---- 更新の条件 ----
def test_updates_every_two_talks_only():
    db, pet = setup()
    talk(db, pet, "やばいめっちゃ好き", hour=23)
    assert maybe_update_personality(db, pet, NOW, run_tx)["updated"] is False  # 1回では更新しない
    talk(db, pet, "なんか楽しい", hour=23)
    r = maybe_update_personality(db, pet, NOW, run_tx)
    assert r["updated"] is True
    assert r["personalityAxes"]["nightowl"] > 0.5 > r["personalityAxes"]["logical"]
    assert maybe_update_personality(db, pet, NOW, run_tx)["updated"] is False  # 同じ材料で二重に更新しない
    assert db.docs[("pets", pet)]["axesUpdatedPoints"] == 2


def test_waits_24h_then_updates_with_one_talk():
    db, pet = setup()
    talk(db, pet, "だからつまり理由はこう")
    assert maybe_update_personality(db, pet, NOW, run_tx)["updated"] is False
    later = NOW + timedelta(hours=25)
    assert maybe_update_personality(db, pet, later, run_tx)["updated"] is True


def test_talk_triggers_update_automatically():
    from petlogic.talk import maybe_update_personality as hooked  # 会話から呼ばれる
    assert hooked is maybe_update_personality


def test_eta_can_be_changed_in_config():
    db, pet = setup()
    db.docs[("config", "game")] = {"personalityEta": 1.0, "personalityMaxShift": 0.05}
    talk(db, pet, "やばい", hour=23)
    talk(db, pet, "めっちゃ", hour=23)
    r = maybe_update_personality(db, pet, NOW, run_tx)
    assert r["personalityAxes"]["nightowl"] == 0.55  # 上限0.05で止まる


def test_exchange_sets_base_and_keeps_axes():
    db, a = setup()
    b = register_device(db, "u2", "devB", NOW)["petId"]
    db.docs[("pets", a)]["personalityAxes"]["nightowl"] = 0.7
    report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                               "gotPetId": b, "transactionId": "t1"}, NOW, run_tx=run_tx)
    pet = db.docs[("pets", a)]
    assert pet["personalityAxes"]["nightowl"] == 0.7 and pet["axesBase"]["nightowl"] == 0.7
    assert pet["axesUpdatedPoints"] == 0.0


# ---- recordProgress ----
def progress(db, uid="u1", **kw):
    return record_progress(db, uid, {"deviceId": "devA", "steps": 9000, "meetCount": 3, **kw}, NOW, run_tx)


def test_record_progress_saves_per_day_and_overwrites():
    db, pet = setup()
    assert progress(db)["date"] == "2026-10-24"
    progress(db, steps=12000)
    docs = [v for (n, _), v in db.docs.items() if n == f"pets/{pet}/dailyStats"]
    assert len(docs) == 1 and docs[0]["steps"] == 12000 and docs[0]["generation"] == 1


def test_record_progress_updates_after_a_day():
    db, pet = setup()
    talk(db, pet, "おはよう")
    later = NOW + timedelta(hours=25)
    r = record_progress(db, "u1", {"deviceId": "devA", "steps": 12000, "meetCount": 5,
                                   "date": "2026-10-24"}, later, run_tx)
    assert r["personalityUpdated"] is True
    axes = db.docs[("pets", pet)]["personalityAxes"]
    assert axes["activity"] > 0.5 and axes["friendly"] > 0.5


def test_record_progress_validation():
    db, _ = setup()
    for bad in ({"steps": -1}, {"steps": "9"}, {"meetCount": 10 ** 6}, {"date": "x"},
                {"date": "2026-10-25"}, {"date": "2026-10-01"}):
        with pytest.raises(ApiError) as e:
            progress(db, **bad)
        assert e.value.code == "invalid-argument"
    with pytest.raises(ApiError) as e:
        progress(db, uid="u2")
    assert e.value.code == "permission-denied"
    with pytest.raises(ApiError) as e:
        record_progress(db, "u1", {"deviceId": "nope"}, NOW, run_tx)
    assert e.value.code == "not-found"
