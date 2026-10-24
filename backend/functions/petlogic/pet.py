"""ペット情報の取得(読むだけ)。ホーム画面の表示に使う。"""
from .errors import ApiError
from .register import validate_device_id


def get_pet(db, uid, device_id):
    """自分の端末にいるペットの、表示用の情報を返す。飼い主のUIDなどは返さない。"""
    validate_device_id(device_id)
    device = db.collection("devices").document(device_id).get()
    if not device.exists:
        raise ApiError("not-found", "この端末は、まだ登録されていません")
    device = device.to_dict()
    if device.get("ownerUid") != uid:
        raise ApiError("permission-denied", "この端末は、あなたのものではありません")

    pet_id = device["currentPetId"]
    pet = db.collection("pets").document(pet_id).get()
    if not pet.exists:
        raise ApiError("not-found", "ペットが見つかりません")
    pet = pet.to_dict()

    created = pet.get("createdAt")
    return {
        "deviceId": device_id,
        "petId": pet_id,
        "name": pet.get("name"),
        "generation": pet.get("generation", 1),
        "personalityAxes": pet.get("personalityAxes", {}),
        "learnedWords": list(pet.get("learnedWords", [])),
        "createdAt": created.isoformat() if hasattr(created, "isoformat") else None,
    }
