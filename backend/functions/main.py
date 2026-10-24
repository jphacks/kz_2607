"""ペット引き継ぎアプリのバックエンド(開発期間中に新規作成)。"""
import os
from datetime import datetime, timezone

from firebase_admin import firestore, initialize_app
from firebase_functions import firestore_fn, https_fn, options, scheduler_fn
from firebase_functions.params import SecretParam

from petlogic.adapters import google_stt, google_tts, http_ai
from petlogic.errors import ApiError
from petlogic.exchange import cancel_exchange, get_exchange_result, report_exchange
from petlogic.letters import generate_letters, get_letters
from petlogic.llm import openai_chat
from petlogic.pet import get_pet
from petlogic.push import fcm_notify, register_push_token
from petlogic.users import upsert_user, upsert_user_quietly
from petlogic.summary import make_summarizer, summarize_handoff
from petlogic.register import register_device
from petlogic.talk import talk

initialize_app()
options.set_global_options(region="asia-northeast1", max_instances=10)

# AIサーバーの鍵。Secret Managerに入れる(コードには書かない)
TALK_API_KEY = SecretParam("TALK_API_KEY")

# 要約・手紙を作るOpenAIの鍵。Secret Managerに入れる。モデル名は functions/.env の OPENAI_MODEL
OPENAI_API_KEY = SecretParam("OPENAI_API_KEY")

_ERROR_CODES = {
    "invalid-argument": https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
    "permission-denied": https_fn.FunctionsErrorCode.PERMISSION_DENIED,
    "not-found": https_fn.FunctionsErrorCode.NOT_FOUND,
    "failed-precondition": https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
    "resource-exhausted": https_fn.FunctionsErrorCode.RESOURCE_EXHAUSTED,
    "unavailable": https_fn.FunctionsErrorCode.UNAVAILABLE,
}


def _now():
    return datetime.now(timezone.utc)


def _run(fn):
    """ApiError を、フロントが受け取れる形のエラーに変える。"""
    try:
        return fn()
    except ApiError as e:
        raise https_fn.HttpsError(_ERROR_CODES[e.code], e.message, e.details())


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
    db = firestore.client()
    result = _run(lambda: register_device(db, uid, data.get("deviceId"), _now()))
    upsert_user_quietly(db, uid, req.auth.token, _now())
    return result


@https_fn.on_call()
def syncUser(req: https_fn.CallableRequest):
    """ログイン中のユーザーの情報(メールアドレスなど)を、users/{uid} に記録する。ログイン後・メール登録後に呼ぶ。"""
    uid = _require_uid(req)
    user = _run(lambda: upsert_user(firestore.client(), uid, req.auth.token, _now()))
    return {"status": "ok", "email": user["email"], "isAnonymous": user["isAnonymous"]}


@https_fn.on_call()
def getPet(req: https_fn.CallableRequest):
    """自分の端末にいるペットの表示用情報を返す(読むだけ)。入力: deviceId。"""
    uid = _require_uid(req)
    data = req.data or {}
    return _run(lambda: get_pet(firestore.client(), uid, data.get("deviceId")))


@https_fn.on_call()
def registerPushToken(req: https_fn.CallableRequest):
    """通知トークンを登録する。入力: token, platform(android / ios)。"""
    uid = _require_uid(req)
    return _run(lambda: register_push_token(firestore.client(), uid, req.data, _now()))


@https_fn.on_call()
def getLetters(req: https_fn.CallableRequest):
    """自分が最初に作ったペットから届いた手紙の一覧(新しい順)。"""
    uid = _require_uid(req)
    return _run(lambda: get_letters(firestore.client(), uid))


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


@https_fn.on_call(invoker="public", timeout_sec=120, memory=options.MemoryOption.MB_512, secrets=[TALK_API_KEY])
def talkToPet(req: https_fn.CallableRequest):
    """録音 → 文字 → AIの返答 → 声。仕様は docs/api.md。"""
    uid = _require_uid(req)
    key = TALK_API_KEY.value
    return _run(
        lambda: talk(
            firestore.client(),
            uid,
            req.data,
            _now(),
            recognize=google_stt,
            ai=lambda url, payload: http_ai(url, payload, key),
            tts=google_tts,
        )
    )


@firestore_fn.on_document_created(document="handoffs/{handoffId}", secrets=[OPENAI_API_KEY], timeout_sec=300)
def summarizeHandoff(event: firestore_fn.Event[firestore_fn.DocumentSnapshot]):
    """交換が確定したあと、手放した代の会話を要約して取っておく(手紙の材料)。"""
    summarize = make_summarizer(OPENAI_API_KEY.value, os.environ.get("OPENAI_MODEL"))
    summarize_handoff(firestore.client(), event.params["handoffId"], summarize, _now())


@scheduler_fn.on_schedule(schedule="0 9 * * *", timezone="Asia/Tokyo", timeout_sec=300, secrets=[OPENAI_API_KEY])
def sendLettersDaily(event: scheduler_fn.ScheduledEvent):
    """毎朝9時(日本時間)。手紙を書く時期のペットに、手紙を作って、通知する。"""
    db = firestore.client()
    key, model = OPENAI_API_KEY.value, os.environ.get("OPENAI_MODEL")
    generate_letters(
        db, _now(),
        lambda system, user: openai_chat(system, user, key, model),
        lambda uid, title, data: fcm_notify(db, uid, title, "手紙を読んでみよう", data),
    )
