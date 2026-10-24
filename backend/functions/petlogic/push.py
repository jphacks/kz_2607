"""通知トークンの登録と、通知の送信。

  users/{uid}/pushTokens/{トークンのハッシュ}  token, platform, updatedAt
"""
import hashlib
import logging

from .errors import ApiError


def _token_id(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:40]


def register_push_token(db, uid, data, now):
    data = data or {}
    token = data.get("token")
    if not isinstance(token, str) or not 20 <= len(token) <= 4096:
        raise ApiError("invalid-argument", "token は、20〜4096文字の文字列にしてください")
    platform = data.get("platform")
    platform = platform if platform in ("android", "ios") else "android"
    ref = db.collection("users").document(uid).collection("pushTokens").document(_token_id(token))
    ref.set({"token": token, "platform": platform, "updatedAt": now})
    return {"status": "ok"}


def fcm_notify(db, uid, title, body, data):
    """そのユーザーの全端末に通知を送る。1台でも届けば True。無効なトークンは消す。"""
    from firebase_admin import messaging

    tokens = db.collection("users").document(uid).collection("pushTokens")
    sent = False
    for snap in tokens.stream():
        token = snap.to_dict().get("token")
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in data.items()},
        )
        try:
            messaging.send(message)
            sent = True
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError):
            tokens.document(snap.id).delete()  # 無効になったトークン
        except Exception as e:
            logging.error("通知の送信に失敗しました: %s: %s", type(e).__name__, str(e)[:300])
    return sent
