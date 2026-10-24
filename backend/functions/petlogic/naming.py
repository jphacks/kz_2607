"""ペットの名前。誕生のときに1回だけつけて、その名前をずっと使う(あとから変えられない)。

  pets/{petId}.name   つけるまでは null
つけられるのは、そのペットを作った本人だけ。名前は、手紙やAIへの送信(petName)に使われる。
"""
import unicodedata

from .errors import ApiError
from .learn import _BLOCKED, _LONG_DIGITS
from .register import validate_device_id
from .store import run_in_transaction

MAX_NAME_CHARS = 12


def clean_name(raw):
    """名前として使えるか確かめて、整えた名前を返す。だめなら ApiError。"""
    if not isinstance(raw, str):
        raise ApiError("invalid-argument", "name は文字列にしてください")
    name = raw.strip()
    if not name or len(name) > MAX_NAME_CHARS:
        raise ApiError("invalid-argument", f"名前は、1〜{MAX_NAME_CHARS}文字にしてください", "invalid_name")
    if any(unicodedata.category(c).startswith("C") for c in name):  # 改行などの制御文字
        raise ApiError("invalid-argument", "名前に使えない文字が入っています", "invalid_name")
    normalized = unicodedata.normalize("NFKC", name).lower()
    if any(b in normalized for b in _BLOCKED) or _LONG_DIGITS.search(normalized):
        raise ApiError("invalid-argument", "その名前は、つけられません", "invalid_name")
    return name


def set_pet_name(db, uid, data, run_tx=run_in_transaction):
    """誕生のときに、名前をつける。入力: deviceId、name。

    つけられるのは、そのペットを作った本人が、そのペットを持っているときだけ。
    もうつけてあるとき: 同じ名前なら、そのまま成功(送り直しOK)。違う名前なら、エラー。
    """
    data = data or {}
    device_id = validate_device_id(data.get("deviceId"))
    name = clean_name(data.get("name"))

    def work(tx):
        device = db.collection("devices").document(device_id).get(transaction=tx)
        if not device.exists:
            raise ApiError("not-found", "この端末は、まだ登録されていません")
        device = device.to_dict()
        if device.get("ownerUid") != uid:
            raise ApiError("permission-denied", "この端末は、あなたのものではありません")
        pet_id = device["currentPetId"]
        pet_ref = db.collection("pets").document(pet_id)
        pet = pet_ref.get(transaction=tx)
        if not pet.exists:
            raise ApiError("not-found", "ペットが見つかりません")
        pet = pet.to_dict()
        if pet.get("creatorUid") != uid:
            raise ApiError("permission-denied", "名前をつけられるのは、そのペットを作った人だけです",
                           "not_creator")
        current = pet.get("name")
        if current:
            if current == name:
                return {"petId": pet_id, "name": current, "alreadySet": True}
            raise ApiError("failed-precondition", "名前は、誕生のときにつけたものから変えられません",
                           "name_already_set", {"name": current})
        tx.update(pet_ref, {"name": name})
        return {"petId": pet_id, "name": name, "alreadySet": False}

    return {"status": "ok", **run_tx(db, work)}
