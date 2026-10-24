"""録音(WAV)の読み取りと検査。"""
import base64
import binascii
import io
import wave

from .errors import ApiError

MAX_SECONDS = 30
MAX_BASE64_CHARS = 5_000_000  # 48kHzで30秒のWAVが、Base64で約3.9MB


def parse_recording(audio_base64):
    """Base64のWAVを検査して、(音声データ, サンプリング周波数, 秒数)を返す。"""
    if not isinstance(audio_base64, str) or not audio_base64:
        raise ApiError("invalid-argument", "録音データがありません", "audio_empty")
    if len(audio_base64) > MAX_BASE64_CHARS:
        raise ApiError("invalid-argument", "録音データが大きすぎます", "audio_too_large")
    try:
        raw = base64.b64decode(audio_base64, validate=True)
        with wave.open(io.BytesIO(raw)) as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            frames = w.getnframes()
            pcm = w.readframes(frames)
    except (binascii.Error, wave.Error, EOFError):
        raise ApiError("invalid-argument", "WAVとして読めません", "bad_wav")
    if channels != 1 or width != 2 or not 8000 <= rate <= 48000:
        raise ApiError(
            "invalid-argument",
            "16bit・モノラル・8000〜48000HzのWAVにしてください",
            "bad_format",
        )
    if frames == 0:
        raise ApiError("invalid-argument", "録音が空です", "audio_empty")
    seconds = frames / rate
    if seconds > MAX_SECONDS:
        raise ApiError("invalid-argument", f"録音は{MAX_SECONDS}秒までです", "audio_too_long")
    return pcm, rate, seconds


def describe_wav(wav_bytes):
    """作ったWAVの、サンプリング周波数とチャンネル数を読む。"""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return {"format": "wav", "sampleRate": w.getframerate(), "channels": w.getnchannels()}
