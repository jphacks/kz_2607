"""音声会話。録音 → 文字 → AIの返答 → 声。"""
import base64
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone

from .adapters import AiCallError
from .audio_codec import CORE2_RATE, wav_to_core2_adpcm
from .errors import ApiError
from .growth import add_talk, stage_config, stage_of
from .personality import maybe_update_personality
from .learn import learn_words
from .memory import load_talk_context
from .register import validate_device_id
from .talklog import record_turn
from .store import run_in_transaction
from .wav import describe_wav, parse_recording

LANGUAGES = ("ja-JP", "en-US")
REPLY_FORMATS = ("wav", "ima_adpcm")
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


def build_ai_payload(text, pet_id, pet, now, context=None, stage=None):
    payload = {"text": text, "petId": pet_id, "hour": now.astimezone(JST).hour,
               "generation": pet.get("generation", 1)}
    for key in ("memories", "pastMemories", "nameMap", "journeys"):  # 思い出の材料(空なら付けない)
        if (context or {}).get(key):
            payload[key] = context[key]
    if pet.get("name"):
        payload["petName"] = pet["name"]
    if stage:
        payload["stage"] = stage  # 姿の段階(baby / child / adult)
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
    ai(url, payload) → {"reply": 返答の文章, "words": 覚えさせたい言葉の候補}。"""
    data = data or {}
    device_id = validate_device_id(data.get("deviceId"))
    language = data.get("languageCode") or "ja-JP"
    if language not in LANGUAGES:
        raise ApiError("invalid-argument", "languageCode は ja-JP か en-US にしてください")
    want_audio = data.get("wantAudio", True)
    if not isinstance(want_audio, bool):
        raise ApiError("invalid-argument", "wantAudio は true か false にしてください")
    reply_format = data.get("replyFormat") or "wav"
    if reply_format not in REPLY_FORMATS:
        raise ApiError("invalid-argument", "replyFormat は wav か ima_adpcm にしてください")
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
    # 音声認識と、思い出の読み込みを、同時に行う(待ち時間を増やさない)
    with ThreadPoolExecutor(max_workers=1) as pool:
        stt = pool.submit(recognize, pcm, rate, language, phrases)
        context = load_talk_context(db, uid, pet_id, pet)
        try:
            transcript, _confidence = stt.result()
        except Exception as e:
            transcript = None
            stt_error = e
    if transcript is None:
        e = stt_error
        logging.error("音声認識に失敗しました: %s: %s", type(e).__name__, str(e)[:500].replace("\n", " "))
        raise ApiError("unavailable", "音声を文字にできませんでした", "stt_failed")
    base = {"petId": pet_id, "durationSec": round(seconds, 2)}
    if not transcript:
        return {"status": "no_speech", "transcript": "", **base}

    config_snap = db.collection("config").document("ai").get()
    config = config_snap.to_dict() if config_snap.exists else {}
    ai_words = []
    if config.get("mode") == "echo":
        reply = f"「{transcript}」って言ったね。"
    else:
        url = config.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ApiError("unavailable", "AIがまだつながっていません", "ai_not_configured")
        try:
            stage = stage_of(pet.get("totalTalks", 0), *stage_config(db))["stage"]
            answer = ai(url, build_ai_payload(transcript, pet_id, pet, now, context, stage))
            reply, ai_words = answer["reply"], answer.get("words", [])
        except AiCallError as e:
            logging.error("AIの呼び出しに失敗しました: %s", e)
            raise ApiError("unavailable", "AIの返答を作れませんでした", "ai_failed")
    reply = reply[:MAX_REPLY_CHARS]

    result = {"status": "ok", "transcript": transcript, "replyText": reply, **base}
    if not want_audio:
        result["audioStatus"] = "skipped"
    else:
        try:
            wav = tts(reply)
            if reply_format == "ima_adpcm":
                adpcm, count = wav_to_core2_adpcm(wav)
                result["replyAudioBase64"] = base64.b64encode(adpcm).decode("ascii")
                result["replyAudio"] = {
                    "format": "ima_adpcm",
                    "sampleRate": CORE2_RATE,
                    "channels": 1,
                    "sampleCount": count,
                    "durationSec": round(count / CORE2_RATE, 2),
                }
            else:
                result["replyAudioBase64"] = base64.b64encode(wav).decode("ascii")
                result["replyAudio"] = describe_wav(wav)
            result["audioStatus"] = "ok"
        except Exception as e:
            logging.error("音声合成に失敗しました: %s: %s", type(e).__name__, str(e)[:500].replace("\n", " "))
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
    result["learnedWords"] = learn_words(db, uid, device_id, pet_id, ai_words, now, run_tx)
    record_turn(db, pet_id, pet.get("generation", 1), transcript, reply, now, run_tx, uid=uid)
    progress = add_talk(db, uid, device_id, pet_id, now, run_tx)
    if progress:
        result["gauge"] = progress["gauge"]
        result["stage"] = progress["stage"]
        result["evolved"] = progress["evolved"]  # この会話で、姿が進化したとき true
        maybe_update_personality(db, pet_id, now, run_tx)  # 失敗しても、会話は止めない
    return result
