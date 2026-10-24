"""ユーザーの記録。ログインしているユーザーの情報を、Firestoreの users/{uid} に取っておく。

  users/{uid}  email, signInProvider, isAnonymous, emailVerified, createdAt, lastSeenAt,
               firstPetId(このユーザーが一番最初に作ったペット。一度決まったら変わらない)
メールアドレスなどは、ログインのトークンから読む(アプリが送った値は信じない)。
"""
import logging



def user_fields(token):
    token = token or {}
    provider = (token.get("firebase") or {}).get("sign_in_provider")
    return {
        "email": token.get("email"),
        "signInProvider": provider,
        "isAnonymous": provider == "anonymous",
        "emailVerified": bool(token.get("email_verified", False)),
    }


def upsert_user(db, uid, token, now):
    """users/{uid} を作る(なければ)か、更新する。返すのは、保存した内容。"""
    ref = db.collection("users").document(uid)
    fields = {**user_fields(token), "lastSeenAt": now}
    if ref.get().exists:
        ref.update(fields)
    else:
        ref.set({**fields, "uid": uid, "createdAt": now})
    return {"uid": uid, **fields}


def upsert_user_quietly(db, uid, token, now):
    """失敗しても、呼び出し元の処理は止めない。"""
    try:
        upsert_user(db, uid, token, now)
    except Exception as e:
        logging.error("ユーザーの記録に失敗しました: %s: %s", type(e).__name__, str(e)[:300])


def oldest_created_pet(db, uid):
    """作成日時が最古のペットのID(同じなら、IDの小さいほう)。いなければ None。"""
    created = [(c.to_dict().get("createdAt"), c.id)
               for c in db.collection("users").document(uid).collection("createdPets").stream()]
    if not created:
        return None
    return min(created, key=lambda x: (x[0] is None, x[0].timestamp() if x[0] is not None else 0, x[1]))[1]


def ensure_first_pet(db, uid, now):
    """users/{uid}.firstPetId を決めて、返す。すでに決まっていれば、そのまま(変えない)。

    ペットがまだなければ None。ペットを作る前から users/{uid} があっても、なくても動く。
    決め方は、作成日時が最古のペットで、いつ誰が呼んでも同じ結果になる(同時に呼ばれても、同じ値を書く)。
    """
    pet_id = oldest_created_pet(db, uid)
    if pet_id is None:
        return None
    ref = db.collection("users").document(uid)
    snap = ref.get()
    data = snap.to_dict() if snap.exists else None
    if data and data.get("firstPetId"):
        return data["firstPetId"]
    if data is None:
        ref.set({"uid": uid, "createdAt": now, "firstPetId": pet_id})
    else:
        ref.update({"firstPetId": pet_id})
    return pet_id


def ensure_first_pet_quietly(db, uid, now):
    """失敗しても、呼び出し元の処理は止めない。"""
    try:
        return ensure_first_pet(db, uid, now)
    except Exception as e:
        logging.error("最初のペットの記録に失敗しました: %s: %s", type(e).__name__, str(e)[:300])
        return None
