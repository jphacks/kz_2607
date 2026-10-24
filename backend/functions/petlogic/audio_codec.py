"""Core2向けの声の変換。WAV → 16kHz・モノラル・IMA-ADPCM(1サンプル4ビット)。

形式: 偶数番目のサンプルが下位4ビット、奇数番目が上位4ビット。
初期状態は、予測値0・ステップ番号0。"""
import io
import wave

CORE2_RATE = 16000

STEP_TABLE = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
    253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
    1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
    3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
]
INDEX_ADJUST = [-1, -1, -1, -1, 2, 4, 6, 8]


def read_wav_mono16(wav_bytes):
    """WAVから、(サンプルのリスト, サンプリング周波数)を取り出す。16bit・モノラルのみ。"""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("16bit・モノラルのWAVだけ扱えます")
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    samples = [int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw) - 1, 2)]
    return samples, rate


def resample(samples, src_rate, dst_rate):
    """周波数を変える。下げるときは、先に3点で平らにして、折り返しの雑音を減らす。"""
    if src_rate == dst_rate or not samples:
        return list(samples)
    if dst_rate < src_rate and len(samples) >= 3:
        padded = [samples[0]] + samples + [samples[-1]]
        samples = [(padded[i] + 2 * padded[i + 1] + padded[i + 2]) // 4 for i in range(len(samples))]
    count = int(len(samples) * dst_rate / src_rate)
    step = src_rate / dst_rate
    out = []
    last = len(samples) - 1
    for i in range(count):
        pos = i * step
        left = int(pos)
        right = min(left + 1, last)
        frac = pos - left
        out.append(int(samples[left] * (1 - frac) + samples[right] * frac))
    return out


def adpcm_encode(samples):
    """16bitのサンプルを、IMA-ADPCMのバイト列にする。"""
    predictor, index = 0, 0
    data = bytearray((len(samples) + 1) // 2)
    for n, sample in enumerate(samples):
        step = STEP_TABLE[index]
        diff = sample - predictor
        code = 0
        if diff < 0:
            code = 8
            diff = -diff
        vpdiff = step >> 3
        if diff >= step:
            code |= 4
            diff -= step
            vpdiff += step
        step >>= 1
        if diff >= step:
            code |= 2
            diff -= step
            vpdiff += step
        step >>= 1
        if diff >= step:
            code |= 1
            vpdiff += step
        predictor += -vpdiff if code & 8 else vpdiff
        predictor = max(-32768, min(32767, predictor))
        index = max(0, min(88, index + INDEX_ADJUST[code & 7]))
        if n % 2 == 0:
            data[n // 2] |= code          # 偶数番目: 下位4ビット
        else:
            data[n // 2] |= code << 4     # 奇数番目: 上位4ビット
    return bytes(data)


def adpcm_decode(data, sample_count):
    """IMA-ADPCMのバイト列を、16bitのサンプルに戻す(テストや確認用)。"""
    predictor, index = 0, 0
    out = []
    for n in range(sample_count):
        byte = data[n // 2]
        code = (byte & 0x0F) if n % 2 == 0 else (byte >> 4)
        step = STEP_TABLE[index]
        vpdiff = step >> 3
        if code & 4:
            vpdiff += step
        if code & 2:
            vpdiff += step >> 1
        if code & 1:
            vpdiff += step >> 2
        predictor += -vpdiff if code & 8 else vpdiff
        predictor = max(-32768, min(32767, predictor))
        index = max(0, min(88, index + INDEX_ADJUST[code & 7]))
        out.append(predictor)
    return out


def wav_to_core2_adpcm(wav_bytes):
    """WAVを、Core2向けのADPCMにする。(バイト列, サンプル数)を返す。"""
    samples, rate = read_wav_mono16(wav_bytes)
    samples = resample(samples, rate, CORE2_RATE)
    return adpcm_encode(samples), len(samples)
