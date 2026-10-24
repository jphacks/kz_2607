import base64
import io
import json
import sys
import threading
import wave
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.adapters import AiCallError, http_ai  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.register import register_device  # noqa: E402
from petlogic.talk import ai_axes, build_ai_payload, talk  # noqa: E402

NOW = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)  # 日本時間12時


def make_wav(seconds=1.0, rate=16000, channels=1, width=2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds) * channels)
    return buf.getvalue()


def b64(wav):
    return base64.b64encode(wav).decode("ascii")


class Fakes:
    def __init__(self, transcript="こんにちは", reply="やあ！", tts_ok=True, ai_ok=True, words=None):
        self.transcript, self.reply, self.tts_ok, self.ai_ok = transcript, reply, tts_ok, ai_ok
        self.words = words or []
        self.ai_calls = []
        self.stt_calls = []

    def recognize(self, pcm, rate, language, phrases):
        self.stt_calls.append((len(pcm), rate, language, phrases))
        return self.transcript, 0.9

    def ai(self, url, payload):
        self.ai_calls.append((url, payload))
        if not self.ai_ok:
            raise AiCallError("down")
        return {"reply": self.reply, "words": self.words}

    def tts(self, text):
        if not self.tts_ok:
            raise RuntimeError("tts down")
        return make_wav(0.5, rate=24000)


def setup(with_ai=True, mode=None):
    db = FakeDb()
    pet = register_device(db, "u1", "devA", NOW)["petId"]
    db.docs[("pets", pet)]["name"] = "モチ"
    cfg = {}
    if with_ai:
        cfg["url"] = "https://ai.example.com/talk"
    if mode:
        cfg["mode"] = mode
    if cfg:
        db.docs[("config", "ai")] = cfg
    return db, pet


def call(db, fakes, now=NOW, uid="u1", **data):
    body = {"deviceId": "devA", "audioBase64": b64(make_wav())}
    body.update(data)
    return talk(db, uid, body, now, fakes.recognize, fakes.ai, fakes.tts, run_tx=run_tx)


def err(*args, **kw):
    with pytest.raises(ApiError) as e:
        call(*args, **kw)
    return e.value


def test_full_conversation():
    db, pet = setup()
    f = Fakes()
    r = call(db, f)
    assert r["status"] == "ok" and r["transcript"] == "こんにちは" and r["replyText"] == "やあ！"
    assert r["audioStatus"] == "ok" and r["petId"] == pet
    assert r["replyAudio"] == {"format": "wav", "sampleRate": 24000, "channels": 1}
    assert base64.b64decode(r["replyAudioBase64"])[:4] == b"RIFF"
    url, payload = f.ai_calls[0]
    assert url == "https://ai.example.com/talk"
    assert payload["text"] == "こんにちは" and payload["petId"] == pet
    assert payload["petName"] == "モチ" and payload["hour"] == 12
    assert payload["personalityAxes"]["active"] == 0.5 and payload["personalityAxes"]["night"] == 0.5
    assert f.stt_calls[0][3] == ["モチ"]


def test_no_speech_does_not_call_ai():
    db, _ = setup()
    f = Fakes(transcript="")
    r = call(db, f)
    assert r["status"] == "no_speech" and f.ai_calls == []


def test_want_audio_false_skips_tts():
    db, _ = setup()
    r = call(db, Fakes(), wantAudio=False)
    assert r["audioStatus"] == "skipped" and "replyAudioBase64" not in r


def test_tts_failure_still_returns_text():
    db, _ = setup()
    r = call(db, Fakes(tts_ok=False))
    assert r["audioStatus"] == "failed" and r["replyText"] == "やあ！"


def test_reply_is_cut_to_200_chars():
    db, _ = setup()
    assert len(call(db, Fakes(reply="あ" * 500))["replyText"]) == 200


def test_ai_failure_and_not_configured():
    db, _ = setup()
    e = err(db, Fakes(ai_ok=False))
    assert (e.code, e.reason) == ("unavailable", "ai_failed")
    db2, _ = setup(with_ai=False)
    e = err(db2, Fakes())
    assert (e.code, e.reason) == ("unavailable", "ai_not_configured")
    db3, _ = setup()
    db3.docs[("config", "ai")]["url"] = "http://insecure.example.com"
    assert err(db3, Fakes()).reason == "ai_not_configured"


def test_echo_mode_bypasses_ai():
    db, _ = setup(with_ai=False, mode="echo")
    f = Fakes(transcript="おはよう")
    r = call(db, f)
    assert "おはよう" in r["replyText"] and f.ai_calls == []


def test_rate_limit_is_6_per_minute_then_resets():
    db, _ = setup()
    f = Fakes()
    for _ in range(6):
        call(db, f)
    e = err(db, f)
    assert (e.code, e.reason) == ("resource-exhausted", "rate_limited") and e.extra["retryAfterSec"] >= 1
    assert call(db, f, now=NOW + timedelta(seconds=61))["status"] == "ok"


def test_other_users_device_and_unknown_device():
    db, _ = setup()
    assert err(db, Fakes(), uid="u2").code == "permission-denied"
    assert err(db, Fakes(), deviceId="nope").code == "not-found"


def test_pet_changed_when_claimed_pet_differs():
    db, pet = setup()
    e = err(db, Fakes(), petId="old-pet")
    assert e.reason == "pet_changed" and e.extra["currentPetId"] == pet
    assert call(db, Fakes(), petId=pet)["status"] == "ok"


def test_pet_changed_during_reply_discards_conversation():
    db, pet = setup()
    f = Fakes()
    original = f.ai

    def swapping_ai(url, payload):
        db.docs[("devices", "devA")]["currentPetId"] = "traded-away"  # 交換が起きた
        return original(url, payload)

    f.ai = swapping_ai
    e = err(db, f)
    assert e.reason == "pet_changed" and e.extra["currentPetId"] == "traded-away"


@pytest.mark.parametrize(
    "audio,reason",
    [
        (b64(make_wav(31)), "audio_too_long"),
        (b64(make_wav(channels=2)), "bad_format"),
        (b64(make_wav(rate=4000)), "bad_format"),
        (b64(make_wav(width=1)), "bad_format"),
        (b64(b"not a wav"), "bad_wav"),
        ("!!!not-base64", "bad_wav"),
        ("", "audio_empty"),
        (b64(make_wav(0)), "audio_empty"),
    ],
)
def test_bad_recordings(audio, reason):
    db, _ = setup()
    e = err(db, Fakes(), audioBase64=audio)
    assert e.code == "invalid-argument" and e.reason == reason


def test_bad_language_and_want_audio():
    db, _ = setup()
    assert err(db, Fakes(), languageCode="fr-FR").code == "invalid-argument"
    assert err(db, Fakes(), wantAudio="yes").code == "invalid-argument"


def test_ai_axes_renamed():
    assert ai_axes({"activity": 0.1, "friendly": 0.2, "logical": 0.3, "nightowl": 0.4}) == {
        "active": 0.1, "affection": 0.2, "logic": 0.3, "night": 0.4,
    }
    assert build_ai_payload("x", "p", {}, NOW) == {"text": "x", "petId": "p", "hour": 12}


# --- AIサーバーへの接続(本物のHTTPサーバーで確かめる) ---

class _Handler(BaseHTTPRequestHandler):
    seen = {}
    reply = {"reply_text": "こんにちは！"}
    status = 200

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).seen = {"key": self.headers.get("X-Api-Key"), "body": json.loads(body)}
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(type(self).reply).encode("utf-8"))

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Handler.reply, _Handler.status = {"reply_text": "こんにちは！"}, 200
    yield f"http://127.0.0.1:{httpd.server_port}/talk"
    httpd.shutdown()


def test_http_ai_sends_key_and_reads_reply(server):
    assert http_ai(server, {"text": "やあ"}, " secret\n") == {"reply": "こんにちは！", "words": []}
    assert _Handler.seen["key"] == "secret" and _Handler.seen["body"] == {"text": "やあ"}


@pytest.mark.parametrize("body", [{"replyText": "A"}, {"reply": "A"}])
def test_http_ai_accepts_other_reply_names(server, body):
    _Handler.reply = body
    assert http_ai(server, {}, None)["reply"] == "A"


@pytest.mark.parametrize("key", ["learn_words", "learnWords", "learned_words"])
def test_http_ai_reads_learn_words(server, key):
    _Handler.reply = {"reply_text": "A", key: ["みかん"]}
    assert http_ai(server, {}, None) == {"reply": "A", "words": ["みかん"]}


@pytest.mark.parametrize("body,status", [({"x": 1}, 200), ({"reply_text": ""}, 200), ({"detail": "bad api key"}, 401)])
def test_http_ai_failures(server, body, status):
    _Handler.reply, _Handler.status = body, status
    with pytest.raises(AiCallError):
        http_ai(server, {}, "k")


# --- 言葉を覚える ---

def test_talk_learns_words_chosen_by_ai():
    db, pet = setup()
    r = call(db, Fakes(words=["みかん", "ねこ"]))
    assert r["learnedWords"] == ["みかん", "ねこ"]
    assert db.docs[("pets", pet)]["learnedWords"] == ["みかん", "ねこ"]
    history = [v for k, v in db.docs.items() if k[0] == f"pets/{pet}/history"]
    assert history and history[0]["type"] == "wordsTaught" and history[0]["words"] == ["みかん", "ねこ"]


def test_talk_without_words_learns_nothing():
    db, pet = setup()
    assert call(db, Fakes())["learnedWords"] == []
    assert db.docs[("pets", pet)]["learnedWords"] == []


def test_learning_failure_does_not_break_the_conversation():
    db, pet = setup()
    f = Fakes(words=["みかん"])
    calls = {"n": 0}

    def flaky_run_tx(d, fn):
        calls["n"] += 1
        if calls["n"] >= 2:  # 1回目は回数制限。2回目(言葉を覚える処理)を失敗させる
            raise RuntimeError("firestore down")
        return run_tx(d, fn)

    r = talk(db, "u1", {"deviceId": "devA", "audioBase64": b64(make_wav())}, NOW,
             f.recognize, f.ai, f.tts, run_tx=flaky_run_tx)
    assert r["status"] == "ok" and r["learnedWords"] == []


def test_nothing_learned_when_pet_changed_during_reply():
    db, pet = setup()
    f = Fakes(words=["みかん"])
    original = f.ai

    def swapping_ai(url, payload):
        db.docs[("devices", "devA")]["currentPetId"] = "traded-away"
        return original(url, payload)

    f.ai = swapping_ai
    assert err(db, f).reason == "pet_changed"
    assert db.docs[("pets", pet)]["learnedWords"] == []


# --- Core2向けの声 ---

def test_reply_format_ima_adpcm():
    db, _ = setup()
    r = call(db, Fakes(), replyFormat="ima_adpcm")
    info = r["replyAudio"]
    assert info["format"] == "ima_adpcm" and info["sampleRate"] == 16000 and info["channels"] == 1
    assert info["sampleCount"] == 8000 and info["durationSec"] == 0.5  # 24kHzの0.5秒 → 16kHz
    assert len(base64.b64decode(r["replyAudioBase64"])) == 4000


def test_reply_format_default_is_wav_and_bad_value_rejected():
    db, _ = setup()
    assert call(db, Fakes())["replyAudio"]["format"] == "wav"
    assert err(db, Fakes(), replyFormat="mp3").code == "invalid-argument"


def test_talk_advances_gauge_and_no_speech_does_not():
    db, pet = setup()
    assert call(db, Fakes(transcript=""))["status"] == "no_speech"
    assert db.docs[("pets", pet)].get("points", 0.0) == 0.0
    r = call(db, Fakes())
    assert r["gauge"] == pytest.approx(1 / 3)
    assert call(db, Fakes())["gauge"] == pytest.approx(2 / 3)
