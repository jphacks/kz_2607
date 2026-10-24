import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.letters import build_prompt, generate_letters, get_letters, interval_days, is_due  # noqa: E402
from petlogic.push import register_push_token  # noqa: E402
from petlogic.register import register_device  # noqa: E402
from petlogic.summary import summarize_handoff  # noqa: E402
from petlogic.talklog import record_turn  # noqa: E402

T0 = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def setup():
    """u1 が作った PA が、u2 のもとへ。PB は u1 のもとへ。"""
    db = FakeDb()
    a = register_device(db, "u1", "devA", T0)["petId"]
    b = register_device(db, "u2", "devB", T0)["petId"]
    db.docs[("pets", a)]["name"] = "モチ"
    record_turn(db, a, 1, "おはよう", "おはよう！", T0, run_tx)
    h = report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                                   "gotPetId": b, "transactionId": "t1"}, T0, run_tx=run_tx)["handoffId"]
    return db, a, b, h


class Notes:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def __call__(self, uid, title, data):
        self.calls.append((uid, title, data))
        return self.ok


def ai(system, user):
    return "元気にしているよ。"


def test_register_adds_created_pets_index():
    db, a, b, _ = setup()
    assert ("users/u1/createdPets", a) in db.docs and ("users/u2/createdPets", b) in db.docs


def test_not_due_before_interval_and_due_after():
    db, a, b, _ = setup()
    n = Notes()
    assert generate_letters(db, T0 + 13 * DAY, ai, n, run_tx) == {"made": 0}
    assert generate_letters(db, T0 + 14 * DAY, ai, n, run_tx) == {"made": 2}  # PA は u1 へ、PB は u2 へ
    assert ("u1", a) in [(c[0], c[2]["petId"]) for c in n.calls]
    assert all(c[2]["type"] == "letter" for c in n.calls)


def test_both_pets_get_letters_to_their_creators():
    db, a, b, _ = setup()
    generate_letters(db, T0 + 14 * DAY, ai, Notes(), run_tx)
    to = {k[0].split("/")[1]: v["recipientUid"] for k, v in db.docs.items() if k[0].endswith("/letters")}
    assert to == {a: "u1", b: "u2"}


def test_same_day_is_not_duplicated_and_interval_restarts():
    db, a, b, _ = setup()
    now = T0 + 14 * DAY
    assert generate_letters(db, now, ai, Notes(), run_tx)["made"] == 2
    assert generate_letters(db, now + timedelta(hours=1), ai, Notes(), run_tx)["made"] == 0
    assert generate_letters(db, now + 13 * DAY, ai, Notes(), run_tx)["made"] == 0
    assert generate_letters(db, now + 14 * DAY, ai, Notes(), run_tx)["made"] == 2


def test_zero_interval_from_config_for_demo():
    db, a, b, _ = setup()
    db.docs[("config", "game")] = {"letterIntervalDays": 0}
    assert interval_days(db) == 0
    assert generate_letters(db, T0 + timedelta(minutes=1), ai, Notes(), run_tx)["made"] == 2


def test_first_generation_and_creator_owned_are_skipped():
    now = T0 + 99 * DAY
    assert not is_due({"generation": 1, "creatorUid": "u1", "ownerUid": "u2", "generationStartedAt": T0}, now, 14)
    assert not is_due({"generation": 3, "creatorUid": "u1", "ownerUid": "u1", "generationStartedAt": T0}, now, 14)
    assert not is_due({"generation": 3, "creatorUid": "u1", "ownerUid": "u2"}, now, 14)  # 古い形式
    assert is_due({"generation": 2, "creatorUid": "u1", "ownerUid": "u2", "generationStartedAt": T0}, now, 14)


def test_ai_failure_falls_back_to_template_and_notify_failure_is_not_fatal():
    db, a, b, _ = setup()

    def bad_ai(system, user):
        raise RuntimeError("down")

    def bad_notify(uid, title, data):
        raise RuntimeError("fcm down")

    assert generate_letters(db, T0 + 14 * DAY, bad_ai, bad_notify, run_tx)["made"] == 2
    letter = next(v for k, v in db.docs.items() if k[0] == f"pets/{a}/letters")
    assert letter["source"] == "template" and letter["notified"] is False and "モチ" in letter["body"]


def test_notified_flag_and_prompt_uses_summaries_without_ids():
    db, a, b, h = setup()
    summarize_handoff(db, h, lambda n, t: "朝のあいさつをしていた。", T0, run_tx)  # PA の1代目の要約(作った人の代)
    db.docs[("pets", a)]["generation"] = 3  # 2代目も終わった想定
    db.docs[("pets/%s/summaries" % a, "2")] = {"generation": 2, "summary": "公園へ散歩に行った話をした。"}
    prompts = []

    def spy(system, user):
        prompts.append(user)
        return "元気だよ"

    db.docs[("pets", a)]["ownerUid"] = "u2"
    generate_letters(db, T0 + 14 * DAY, spy, Notes(True), run_tx)
    mine = next(p for p in prompts if "モチ" in p)
    assert "公園へ散歩" in mine and "朝のあいさつ" not in mine  # 作った人の代(1)は含めない
    assert "u1" not in mine and "u2" not in mine
    letter = next(v for k, v in db.docs.items() if k[0] == f"pets/{a}/letters")
    assert letter["notified"] is True


def test_prompt_without_summaries_says_just_fine():
    assert "元気に暮らしている" in build_prompt({"name": "モチ"}, [])


def test_get_letters_returns_only_own_newest_first():
    db, a, b, _ = setup()
    generate_letters(db, T0 + 14 * DAY, ai, Notes(), run_tx)
    generate_letters(db, T0 + 30 * DAY, ai, Notes(), run_tx)
    mine = get_letters(db, "u1")["letters"]
    assert [x["petId"] for x in mine] == [a, a] and mine[0]["createdAt"] > mine[1]["createdAt"]
    assert mine[0]["petName"] == "モチ" and mine[0]["body"] == "元気にしているよ。"
    assert get_letters(db, "nobody") == {"letters": []}


def test_register_push_token_validation_and_idempotent():
    db = FakeDb()
    tok = "x" * 40
    register_push_token(db, "u1", {"token": tok, "platform": "ios"}, T0)
    register_push_token(db, "u1", {"token": tok}, T0)
    docs = [k for k in db.docs if k[0] == "users/u1/pushTokens"]
    assert len(docs) == 1 and db.docs[docs[0]]["platform"] == "android"
    for bad in (None, "short", 123, "x" * 5000):
        with pytest.raises(ApiError) as e:
            register_push_token(db, "u1", {"token": bad}, T0)
        assert e.value.code == "invalid-argument"
