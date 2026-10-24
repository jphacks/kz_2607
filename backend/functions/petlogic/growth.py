"""成長の記録。会話・歩数・すれ違いをポイントにして、ゲージを進める。

記録の置き場所:
  pets/{petId}                points(貯めたポイント)、gauge(0〜1)
  pets/{petId}/events/{key}   記録1回分。同じ eventKey の再送は、足さない
ゲージは、飼い主が変わる(交換が確定する)たびに、0に戻る。
"""
import math

from .errors import ApiError
from .register import validate_device_id
from .store import run_in_transaction

# 1回の記録で受け付ける上限(アプリの不具合で、一度に満タンになるのを防ぐ)
LIMITS = {"nTalk": 100, "steps": 100_000, "nMeet": 50}
# ポイントの重み: 会話1回、1000歩、すれ違い1回
W_TALK, W_STEP_PER_1000, W_MEET = 1.0, 1.0, 3.0
FULL_POINTS = 120.0  # このポイントでゲージが満タン


def gauge_of(points):
    return min(max(points, 0.0) / FULL_POINTS, 1.0)


def _count(value, name):
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ApiError("invalid-argument", f"{name} は、0以上の数にしてください")
    return min(int(value), LIMITS[name])


def gained_points(n_talk, steps, n_meet):
    return W_TALK * n_talk + W_STEP_PER_1000 * steps / 1000.0 + W_MEET * n_meet


def require_full_gauge(db):
    """交換にゲージ満タンを求めるか。Firestoreの config/game の requireFullGauge(既定は求めない)。"""
    snap = db.collection("config").document("game").get()
    return bool(snap.exists and snap.to_dict().get("requireFullGauge") is True)


def record_progress(db, uid, data, now, run_tx=run_in_transaction):
    data = data or {}
    device_id = validate_device_id(data.get("deviceId"))
    n_talk = _count(data.get("nTalk"), "nTalk")
    steps = _count(data.get("steps"), "steps")
    n_meet = _count(data.get("nMeet"), "nMeet")
    if n_talk == 0 and steps == 0 and n_meet == 0:
        raise ApiError("invalid-argument", "nTalk、steps、nMeet のどれかが必要です")
    key = data.get("eventKey")
    if key is not None and (not isinstance(key, str) or not 1 <= len(key) <= 80 or "/" in key):
        raise ApiError("invalid-argument", "eventKey は、/ を含まない1〜80文字にしてください")

    def work(tx):
        device = db.collection("devices").document(device_id).get(transaction=tx)
        if not device.exists:
            raise ApiError("not-found", "この端末は、まだ登録されていません")
        device = device.to_dict()
        if device.get("ownerUid") != uid:
            raise ApiError("permission-denied", "この端末は、あなたのものではありません")

        pet_id = device["currentPetId"]
        pet_ref = db.collection("pets").document(pet_id)
        pet_snap = pet_ref.get(transaction=tx)
        if not pet_snap.exists:
            raise ApiError("not-found", "ペットが見つかりません")
        pet = pet_snap.to_dict()
        points = pet.get("points", 0.0)

        events = pet_ref.collection("events")
        event_ref = events.document(key) if key else events.document()
        if key and event_ref.get(transaction=tx).exists:  # 再送。足さない
            return {"status": "already_recorded", "petId": pet_id, "points": points, "gauge": gauge_of(points)}

        gained = gained_points(n_talk, steps, n_meet)
        points += gained
        tx.update(pet_ref, {"points": points, "gauge": gauge_of(points)})
        tx.set(event_ref, {"ownerUid": uid, "generation": pet.get("generation", 1),
                           "nTalk": n_talk, "steps": steps, "nMeet": n_meet,
                           "points": gained, "createdAt": now})
        return {"status": "recorded", "petId": pet_id, "points": points, "gauge": gauge_of(points)}

    return run_tx(db, work)
