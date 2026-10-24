import io
import math
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from petlogic.audio_codec import (  # noqa: E402
    adpcm_decode, adpcm_encode, read_wav_mono16, resample, wav_to_core2_adpcm,
)


def sine(rate, seconds, freq=440, amp=12000):
    return [int(amp * math.sin(2 * math.pi * freq * i / rate)) for i in range(int(rate * seconds))]


def to_wav(samples, rate):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(s.to_bytes(2, "little", signed=True) for s in samples))
    return buf.getvalue()


def test_roundtrip_is_close_to_original():
    original = sine(16000, 0.5)
    decoded = adpcm_decode(adpcm_encode(original), len(original))
    signal = sum(s * s for s in original)
    noise = sum((a - b) ** 2 for a, b in zip(original, decoded))
    assert 10 * math.log10(signal / noise) > 20  # 信号対雑音比が20dB以上


def test_size_is_half_byte_per_sample():
    assert len(adpcm_encode([0] * 10)) == 5
    assert len(adpcm_encode([0] * 11)) == 6
    assert adpcm_encode([]) == b""


def test_nibble_order_even_is_low_bits():
    # 最初の2サンプル: 大きい正の値(符号なし・大きい符号) と 大きい負の値
    data = adpcm_encode([30000, -30000])
    low, high = data[0] & 0x0F, data[0] >> 4
    assert low & 8 == 0 and high & 8 == 8  # 偶数番目(正)が下位、奇数番目(負)が上位


def test_known_first_codes():
    # 予測値0・ステップ7の状態から、1000は最大の符号7になる
    assert adpcm_encode([1000])[0] & 0x0F == 7
    assert adpcm_encode([-1000])[0] & 0x0F == 15


def test_resample_length_and_identity():
    assert len(resample(sine(24000, 1.0), 24000, 16000)) == 16000
    x = [1, 2, 3]
    assert resample(x, 16000, 16000) == x and resample([], 24000, 16000) == []


def test_wav_to_core2_adpcm():
    data, count = wav_to_core2_adpcm(to_wav(sine(24000, 0.5), 24000))
    assert count == 8000 and len(data) == 4000


def test_read_wav_rejects_stereo():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00" * 8)
    with pytest.raises(ValueError):
        read_wav_mono16(buf.getvalue())
