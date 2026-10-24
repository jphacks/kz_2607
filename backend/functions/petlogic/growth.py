"""成長の記録。会話するたびに、ペットのゲージが進む。

  pets/{petId}  points(会話の回数)、gauge(0〜1)
ゲージは、飼い主が変わる(交換が確定する)たびに、0に戻る。
"""
import logging

from .store import run_in_transaction

TALKS_TO_FULL = 3  # 会話がこの回数で、ゲージが満タン


def gauge_of(points):
    return min(max(points, 0.0) / TALKS_TO_FULL, 1.0)


def require_full_gauge(db):
    """交換にゲージ満タンを求めるか。Firestoreの config/game の requireFullGauge(既定は求めない)。"""
    snap = db.collection("config").document("game").get()
    return bool(snap.exists and snap.to_dict().get("requireFullGauge") is True)


def add_talk(db, uid, device_id, pet_id, now, run_tx=run_in_transaction):
    """会話1回分を足す。いまの持ち主の、いまのペットだけ。失敗しても会話は止めず、Noneを返す。"""

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
        points = pet.to_dict().get("points", 0.0) + 1
        tx.update(pet_ref, {"points": points, "gauge": gauge_of(points)})
        return {"points": points, "gauge": gauge_of(points)}

    try:
        return run_tx(db, work)
    except Exception as e:
        logging.error("ゲージの更新に失敗しました: %s: %s", type(e).__name__, str(e)[:300])
        return None
