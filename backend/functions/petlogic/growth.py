"""成長の記録。会話するたびに、ペットのゲージが進み、姿(赤ちゃん→子供→大人)が育つ。

  pets/{petId}  points(会話の回数)、gauge(0〜1)、totalTalks(会話の累計)
ゲージは、飼い主が変わる(交換が確定する)たびに、0に戻る。
累計は、交換しても引き継ぐ。姿は、累計の会話回数で決まる。
"""
import logging

from .store import run_in_transaction

TALKS_TO_FULL = 10  # 会話がこの回数で、ゲージが満タン(既定。デモ用。config/game の talksToFull で変える。本番は100)
STAGES = ("baby", "child", "adult")  # 赤ちゃん → 子供 → 大人
DEFAULT_CHILD_AT = 30  # 累計の会話がこの回数で、子供になる
DEFAULT_ADULT_AT = 100  # 累計の会話がこの回数で、大人になる


def gauge_of(points, full=TALKS_TO_FULL):
    return min(max(points, 0.0) / max(full, 1), 1.0)


def talks_to_full(db):
    """ゲージが満タンになる会話の回数。config/game の talksToFull で変えられる(既定は10)。"""
    snap = db.collection("config").document("game").get()
    v = (snap.to_dict() if snap.exists else {}).get("talksToFull")
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 1 else TALKS_TO_FULL


def stage_config(db):
    """子供・大人になる会話の回数。config/game の stageChildAt・stageAdultAt で変えられる。"""
    snap = db.collection("config").document("game").get()
    cfg = snap.to_dict() if snap.exists else {}

    def number(key, default):
        v = cfg.get(key)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 1 else default

    child, adult = number("stageChildAt", DEFAULT_CHILD_AT), number("stageAdultAt", DEFAULT_ADULT_AT)
    return (child, adult) if child < adult else (DEFAULT_CHILD_AT, DEFAULT_ADULT_AT)


def stage_of(total_talks, child_at, adult_at):
    """累計の会話回数から、姿の段階を決める。"""
    total = max(int(total_talks or 0), 0)
    index = 0 if total < child_at else 1 if total < adult_at else 2
    next_at = (child_at, adult_at, None)[index]
    return {"stage": STAGES[index], "stageIndex": index + 1, "nextStageAt": next_at,
            "talksToNextStage": None if next_at is None else next_at - total}


def require_full_gauge(db):
    """交換にゲージ満タンを求めるか。Firestoreの config/game の requireFullGauge(既定は求めない)。"""
    snap = db.collection("config").document("game").get()
    return bool(snap.exists and snap.to_dict().get("requireFullGauge") is True)


def add_talk(db, uid, device_id, pet_id, now, run_tx=run_in_transaction):
    """会話1回分を足す。いまの持ち主の、いまのペットだけ。失敗しても会話は止めず、Noneを返す。"""

    child_at, adult_at = stage_config(db)
    full = talks_to_full(db)

    def work(tx):
        device = db.collection("devices").document(device_id).get(transaction=tx)
        if not device.exists:
            return None
        device = device.to_dict()
        if device.get("ownerUid") != uid or device.get("currentPetId") != pet_id:
            return None
        pet_ref = db.collection("pets").document(pet_id)
        pet = pet_ref.get(transaction=tx)
        if not pet.exists:
            return None
        pet = pet.to_dict()
        points = pet.get("points", 0.0) + 1
        total = pet.get("totalTalks", 0) + 1
        tx.update(pet_ref, {"points": points, "gauge": gauge_of(points, full), "totalTalks": total})
        before = stage_of(total - 1, child_at, adult_at)["stage"]
        now_stage = stage_of(total, child_at, adult_at)
        return {"points": points, "gauge": gauge_of(points, full), "totalTalks": total,
                "stage": now_stage["stage"], "evolved": now_stage["stage"] != before}

    try:
        return run_tx(db, work)
    except Exception as e:
        logging.error("ゲージの更新に失敗しました: %s: %s", type(e).__name__, str(e)[:300])
        return None
