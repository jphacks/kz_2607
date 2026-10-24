"""ペット引き継ぎアプリのバックエンド(開発期間中に新規作成)。"""
from datetime import datetime, timezone

from firebase_admin import firestore, initialize_app
from firebase_functions import https_fn, options

from petlogic.errors import ApiError
from petlogic.exchange import cancel_exchange, get_exchange_result, report_exchange
from petlogic.register import register_device

initialize_app()
options.set_global_options(region="asia-northeast1", max_instances=10)

_ERROR_CODES = {
    "invalid-argument": https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
    "permission-denied": https_fn.FunctionsErrorCode.PERMISSION_DENIED,
    "not-found": https_fn.FunctionsErrorCode.NOT_FOUND,
    "failed-precondition": https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
}


def _now():
    return datetime.now(timezone.utc)


def _run(fn):
    """ApiError を、フロントが受け取れる形のエラーに変える。"""
    try:
        return fn()
    except ApiError as e:
        details = {"reason": e.reason} if e.reason else None
        raise https_fn.HttpsError(_ERROR_CODES[e.code], e.message, details)


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
    return _run(lambda: register_device(firestore.client(), uid, data.get("deviceId"), _now()))


@https_fn.on_call()
def reportExchange(req: https_fn.CallableRequest):
    """すれ違い交換の確定を報告する。仕様は docs/api.md。"""
    uid = _require_uid(req)
    return _run(lambda: report_exchange(firestore.client(), uid, req.data, _now()))


@https_fn.on_call()
def getExchangeResult(req: https_fn.CallableRequest):
    """交換の結果を確認する(読むだけ)。"""
    uid = _require_uid(req)
    return _run(lambda: get_exchange_result(firestore.client(), uid, req.data))


@https_fn.on_call()
def cancelExchange(req: https_fn.CallableRequest):
    """まだ確定していない交換を取り消す。"""
    uid = _require_uid(req)
    return _run(lambda: cancel_exchange(firestore.client(), uid, req.data, _now()))
