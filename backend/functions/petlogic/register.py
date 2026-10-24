"""端末の登録。端末ごとに、ペットを1匹だけ結びつける。"""
import re

from google.api_core.exceptions import AlreadyExists

from .errors import ApiError

DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

# 性格の6つの軸。0.0〜1.0。生まれたときは、すべて中間の値。
AXIS_NAMES = ("activity", "friendly", "talkative", "logical", "curious", "nightowl")


RegisterError = ApiError  # 以前の名前でも、使えるようにしておく


def validate_device_id(device_id):
    if not isinstance(device_id, str) or not DEVICE_ID_PATTERN.match(device_id):
        raise RegisterError(
            "invalid-argument",
            "deviceId は、英数字と _ . : - だけの、1〜64文字の文字列にしてください",
        )
    return device_id


def new_pet(uid, now):
    return {
        "creatorUid": uid,
        "ownerUid": uid,  # いまの持ち主。交換のたびに変わる
        "generationStartedAt": now,  # いまの代が始まった日時
        "createdAt": now,
        "name": None,
        "personalityAxes": {name: 0.5 for name in AXIS_NAMES},
        "learnedWords": [],
        "points": 0.0,
        "gauge": 0.0,
        "generation": 1,  # 手渡しされるたびに、1ずつ増える
    }


def _existing_result(device_id, device, uid):
    if device.get("ownerUid") != uid:
        raise RegisterError("permission-denied", "この端末は、別のユーザーが登録済みです")
    return {"deviceId": device_id, "petId": device["currentPetId"], "isNew": False}


def register_device(db, uid, device_id, now):
    """端末を登録して、結びついたペットを返す。2回目以降は、同じペットを返す。"""
    validate_device_id(device_id)
    device_ref = db.collection("devices").document(device_id)

    snap = device_ref.get()
    if snap.exists:
        return _existing_result(device_id, snap.to_dict(), uid)

    pet_ref = db.collection("pets").document()
    batch = db.batch()
    batch.create(pet_ref, new_pet(uid, now))
    batch.create(
        device_ref,
        {"ownerUid": uid, "currentPetId": pet_ref.id, "createdAt": now},
    )
    try:
        batch.commit()
    except AlreadyExists:
        # ほぼ同時に、別の呼び出しが先に登録した。そちらの結果を返す。
        return _existing_result(device_id, device_ref.get().to_dict(), uid)

    return {"deviceId": device_id, "petId": pet_ref.id, "isNew": True}
