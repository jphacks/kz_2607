"""外部サービス(Google音声認識、Google音声合成、AIサーバー)への接続。"""
import json
import urllib.error
import urllib.request

AI_TIMEOUT_SEC = 60
TTS_VOICE = "ja-JP-Neural2-B"
TTS_RATE = 24000


class AiCallError(Exception):
    pass


def google_stt(pcm, rate, language, phrases):
    """音声データを文字にする。(文字, 確信度)を返す。聞き取れなければ、文字は空。"""
    from google.cloud import speech

    client = speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=rate,
        language_code=language,
        enable_automatic_punctuation=True,
        speech_contexts=[speech.SpeechContext(phrases=phrases)] if phrases else [],
    )
    response = client.recognize(config=config, audio=speech.RecognitionAudio(content=pcm))
    texts, confidences = [], []
    for result in response.results:
        best = result.alternatives[0]
        texts.append(best.transcript)
        confidences.append(best.confidence)
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return "".join(texts).strip(), confidence


def google_tts(text):
    """文章を声にする。ヘッダー付きのWAV(24kHz・モノラル・16bit)を返す。"""
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code="ja-JP", name=TTS_VOICE),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16, sample_rate_hertz=TTS_RATE
        ),
    )
    return response.audio_content


def http_ai(url, payload, api_key):
    """AIサーバーに送って、{"reply": 返答の文章, "words": 覚えさせたい言葉の候補} を受け取る。"""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key.strip()
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=AI_TIMEOUT_SEC) as res:
            body = json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise AiCallError(str(e))
    if not isinstance(body, dict):
        raise AiCallError("AIの返事の形が違います")
    words = []
    for key in ("learn_words", "learnWords", "learned_words"):
        if isinstance(body.get(key), list):
            words = body[key]
            break
    for key in ("reply_text", "replyText", "reply"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return {"reply": value.strip(), "words": words}
    raise AiCallError("AIの返事に、文章がありません")
