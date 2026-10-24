"""音声会話。録音 → 文字 → AIの返答 → 声。"""
import base64
from datetime import timedelta, timezone

from .adapters import AiCallError
from .errors import ApiError
from .register import validate_device_id
from .store import run_in_transaction
from .wav import describe_wav, parse_recording

LANGUAGES = ("ja-JP", "en-US")
RATE_LIMIT_PER_MINUTE = 6
MAX_REPLY_CHARS = 200
JST = timezone(timedelta(hours=9))

# AIサーバーが使う軸の名前に、直す
AI_AXIS_NAMES = {
    "activity": "active",
    "friendly": "affection",
    "talkative": "talkative",
    "logical": "logic",
    "curious": "curious",
    "nightowl": "night",
}


def ai_axes(axes):
    axes = axes or {}
    return {ai: axes[mine] for mine, ai in AI_AXIS_NAMES.items() if mine in axes}


def build_ai_payload(text, pet_id, pet, now):
    payload = {"text": text, "petId": pet_id, "hour": now.astimezone(JST).hour}
    if pet.get("name"):
        payload["petName"] = pet["name"]
    axes = ai_axes(pet.get("personalityAxes"))
    if axes:
        payload["personalityAxes"] = axes
    return payload


def check_rate_limit(db, uid, now, run_tx):
    """1分間に、6回まで。"""

    def work(tx):
        ref = db.collection("users").document(uid).collection("limits").document("talk")
        snap = ref.get(transaction=tx)
        data = snap.to_dict() if snap.exists else {}
        start = data.get("windowStart")
        count = data.get("count", 0)
        if start is None or (now - start).total_seconds() >= 60:
            tx.set(ref, {"windowStart": now, "count": 1})
            return
        if count >= RATE_LIMIT_PER_MINUTE:
            wait = max(1, int(60 - (now - start).total_seconds()))
            raise ApiError(
                "resource-exhausted",
                "話しかけすぎです。少し待ってください",
                "rate_limited",
                {"retryAfterSec": wait},
            )
        tx.set(ref, {"windowStart": start, "count": count + 1})

    run_tx(db, work)


def talk(db, uid, data, now, recognize, ai, tts, run_tx=run_in_transaction):
    """recognize / ai / tts は、外部サービスへの接続(テストでは差し替える)。
    ai(url, payload) → 返答の文章。"""
    data = data or {}
    device_id = validate_device_id(data.get("deviceId"))
    language = data.get("languageCode") or "ja-JP"
    if language not in LANGUAGES:
        raise ApiError("invalid-argument", "languageCode は ja-JP か en-US にしてください")
    want_audio = data.get("wantAudio", True)
    if not isinstance(want_audio, bool):
        raise ApiError("invalid-argument", "wantAudio は true か false にしてください")
    claimed_pet = data.get("petId")

    device_ref = db.collection("devices").document(device_id)
    device_snap = device_ref.get()
    if not device_snap.exists:
        raise ApiError("not-found", "端末が登録されていません")
    device = device_snap.to_dict()
    if device.get("ownerUid") != uid:
        raise ApiError("permission-denied", "自分の端末ではありません")
    pet_id = device["currentPetId"]
    if claimed_pet is not None and claimed_pet != pet_id:
        raise ApiError(
            "failed-precondition",
            "端末のペットが変わっています",
            "pet_changed",
            {"currentPetId": pet_id},
        )

    pcm, rate, seconds = parse_recording(data.get("audioBase64"))
    check_rate_limit(db, uid, now, run_tx)

    pet_snap = db.collection("pets").document(pet_id).get()
    if not pet_snap.exists:
        raise ApiError("not-found", "ペットが見つかりません")
    pet = pet_snap.to_dict()

    phrases = [pet["name"]] if pet.get("name") else []
    try:
        transcript, _confidence = recognize(pcm, rate, language, phrases)
    except Exception:
        raise ApiError("unavailable", "音声を文字にできませんでした", "stt_failed")
    base = {"petId": pet_id, "durationSec": round(seconds, 2)}
    if not transcript:
        return {"status": "no_speech", "transcript": "", **base}

    config_snap = db.collection("config").document("ai").get()
    config = config_snap.to_dict() if config_snap.exists else {}
    if config.get("mode") == "echo":
        reply = f"「{transcript}」って言ったね。"
    else:
        url = config.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ApiError("unavailable", "AIがまだつながっていません", "ai_not_configured")
        try:
            reply = ai(url, build_ai_payload(transcript, pet_id, pet, now))
        except AiCallError:
            raise ApiError("unavailable", "AIの返答を作れませんでした", "ai_failed")
    reply = reply[:MAX_REPLY_CHARS]

    result = {"status": "ok", "transcript": transcript, "replyText": reply, **base}
    if not want_audio:
        result["audioStatus"] = "skipped"
    else:
        try:
            wav = tts(reply)
            result["replyAudioBase64"] = base64.b64encode(wav).decode("ascii")
            result["replyAudio"] = describe_wav(wav)
            result["audioStatus"] = "ok"
        except Exception:
            result["audioStatus"] = "failed"  # 文章は返す

    # 返答を作っている間に、交換でペットが変わっていないか
    now_pet = device_ref.get().to_dict().get("currentPetId")
    if now_pet != pet_id:
        raise ApiError(
            "failed-precondition",
            "返答を作っている間に、ペットが変わりました",
            "pet_changed",
            {"currentPetId": now_pet},
        )
    return result
