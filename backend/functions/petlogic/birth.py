"""誕生のときの性格。6問の回答から、6軸の初期値を決める(1回だけ・変更不可)。

  pets/{petId}.personalityAxes      初期値(0.2 / 0.4 / 0.6 / 0.8)
  pets/{petId}.axesBase             同じ値。性格が動ける幅の基準(その飼い主に渡された時点の値)
  pets/{petId}.birthAnswers         回答(0〜3の6個。軸の順: AXIS_NAMES)
  pets/{petId}.questionnaireVersion 質問のバージョン
  pets/{petId}.birthTrait           誕生時にいちばん強い軸(AIの名前。同じ値なら active→affection→…の順)
値は、アプリの計算ではなく、回答からサーバーで決める。
"""
from .appearance import appearance_of
from .errors import ApiError
from .register import AXIS_NAMES, validate_device_id
from .store import run_in_transaction
from .talk import AI_AXIS_NAMES

LEVELS = (0.2, 0.4, 0.6, 0.8)  # 回答 0〜3 に対応する値
TRAIT_ORDER = ("activity", "friendly", "talkative", "logical", "curious", "nightowl")  # 同じ値のときの優先順


def parse_answers(raw):
    """回答を、軸の順(AXIS_NAMES)の0〜3の6個にそろえる。リスト(軸の順)でも、軸の名前をキーにした辞書でもよい。"""
    if isinstance(raw, dict):
        if set(raw) != set(AXIS_NAMES):
            raise ApiError("invalid-argument", f"answers のキーは {list(AXIS_NAMES)} にしてください", "invalid_answers")
        raw = [raw[n] for n in AXIS_NAMES]
    if not isinstance(raw, (list, tuple)) or len(raw) != len(AXIS_NAMES):
        raise ApiError("invalid-argument", f"answers は {len(AXIS_NAMES)} 個にしてください", "invalid_answers")
    if any(isinstance(a, bool) or not isinstance(a, (int, float)) or a != int(a) or not 0 <= a <= 3 for a in raw):
        raise ApiError("invalid-argument", "answers は 0〜3 の整数にしてください", "invalid_answers")
    return [int(a) for a in raw]


def axes_of(answers):
    return {name: LEVELS[a] for name, a in zip(AXIS_NAMES, answers)}


def birth_trait(axes):
    """いちばん強い軸(AIの名前)。同じ値なら TRAIT_ORDER の順。"""
    top = max(TRAIT_ORDER, key=lambda n: (axes[n], -TRAIT_ORDER.index(n)))
    return AI_AXIS_NAMES[top]


def set_initial_personality(db, uid, data, now, run_tx=run_in_transaction):
    """入力: deviceId、answers(0〜3が6個)、questionnaireVersion(1以上の整数)。axes は表示用なので使わない。

    できるのは、そのペットを作った本人が、いまも持っていて、交換前の1代目で、まだ話していないとき。
    同じ回答を送り直したら、成功(alreadySet: true)。違う回答なら、エラー。
    """
    data = data or {}
    device_id = validate_device_id(data.get("deviceId"))
    answers = parse_answers(data.get("answers"))
    version = data.get("questionnaireVersion")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ApiError("invalid-argument", "questionnaireVersion は 1 以上の整数にしてください", "invalid_version")

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
            raise ApiError("permission-denied", "決められるのは、そのペットを作った人だけです", "not_creator")
        if pet.get("birthAnswers") is not None:
            if pet["birthAnswers"] == answers and pet.get("questionnaireVersion") == version:
                already = True
            else:
                raise ApiError("failed-precondition", "性格は、誕生のときに決めたものから変えられません",
                               "personality_already_set")
        else:
            already = False
            if pet.get("ownerUid") != uid or pet.get("generation", 1) != 1 or pet.get("totalTalks", 0) > 0:
                raise ApiError("failed-precondition", "性格を決められるのは、交換も会話もする前だけです",
                               "personality_not_allowed")
            axes = axes_of(answers)
            tx.update(pet_ref, {"personalityAxes": axes, "axesBase": dict(axes), "axesUpdatedPoints": 0.0,
                                "axesUpdatedAt": now, "birthAnswers": answers, "questionnaireVersion": version,
                                "birthTrait": birth_trait(axes)})
            pet = {**pet, "personalityAxes": axes, "birthTrait": birth_trait(axes)}
        return {"petId": pet_id, "personalityAxes": pet["personalityAxes"], "birthTrait": pet["birthTrait"],
                "appearance": appearance_of(pet_id, pet["personalityAxes"], "baby"), "alreadySet": already}

    return {"status": "ok", **run_tx(db, work)}
