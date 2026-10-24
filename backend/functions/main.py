"""ペット引き継ぎアプリのバックエンド(開発期間中に新規作成)。"""
from datetime import datetime, timezone

from firebase_admin import firestore, initialize_app
from firebase_functions import https_fn, options

from petlogic.register import RegisterError, register_device

initialize_app()
options.set_global_options(region="asia-northeast1", max_instances=10)

_ERROR_CODES = {
    "invalid-argument": https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
    "permission-denied": https_fn.FunctionsErrorCode.PERMISSION_DENIED,
}


def _require_uid(req: https_fn.CallableRequest) -> str:
    if req.auth is None:
        raise https_fn.HttpsError(
            https_fn.FunctionsErrorCode.UNAUTHENTICATED, "ログインしてから呼んでください"
        )
    return req.auth.uid


@https_fn.on_call()
def ping(req: https_fn.CallableRequest):
    """動作確認用。デプロイできているかを確かめる。"""
    return {"ok": True}


@https_fn.on_call()
def registerDevice(req: https_fn.CallableRequest):
    """端末を登録し、ペットを結びつける。入力: deviceId。出力: deviceId, petId, isNew。"""
    uid = _require_uid(req)
    data = req.data or {}
    try:
        return register_device(
            firestore.client(), uid, data.get("deviceId"), datetime.now(timezone.utc)
        )
    except RegisterError as e:
        raise https_fn.HttpsError(_ERROR_CODES[e.code], e.message)
