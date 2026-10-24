"""ユーザーの記録。ログインしているユーザーの情報を、Firestoreの users/{uid} に取っておく。

  users/{uid}  email, signInProvider, isAnonymous, emailVerified, createdAt, lastSeenAt
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
