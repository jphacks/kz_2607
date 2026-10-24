"""性格の更新。飼い主の話し方・関わり方に、ペットの6軸が少しずつ近づく。

  pets/{petId}
    personalityAxes  6軸(0〜1)
    axesBase         この飼い主に渡された時点の値(影響の上限の基準)
    axesUpdatedPoints / axesUpdatedAt  前回の更新時点
  pets/{petId}/dailyStats/{日付}   アプリが送る、1日分の歩数とすれ違い数

更新式: v ← v + η·c·(L − v)、そのあと base ± C に収める。
L は飼い主の水準(0〜1)。c は、材料の多さによる信頼度(0〜1)。
理屈っぽさ・好奇心は、単語リストと文字の重なりで、簡易に計算する。
"""
import logging
from datetime import timedelta, timezone

from .errors import ApiError
from .register import validate_device_id
from .store import run_in_transaction
from .talklog import read_turns

JST = timezone(timedelta(hours=9))
UPDATE_EVERY_TALKS = 2  # 会話がこの回数ふえたら更新する(式②: ΔP ≥ P_full ÷ 6。P_full が満タンの10回(デモ)なら約2。本番は設定で)
DEFAULT_TOPIC_WEIGHT = 0.5  # 好奇心のうち「新しい話題」の割合。0にすると、質問の割合だけで決める
UPDATE_AFTER_HOURS = 24  # 前回から、この時間たっていれば、1回でも更新する
DEFAULT_ETA = 0.12  # 近づく速さ
DEFAULT_MAX_SHIFT = 0.2  # 1人の飼い主で動ける幅
STEPS_FULL = 12000  # 1日の平均歩数が、これで活発さ1.0
MEETS_FULL = 5  # 1日の平均すれ違いが、これで人懐っこさ1.0
TALKS_FULL = 20  # 1日の平均会話が、これでおしゃべり1.0
CONFIDENT_TALKS = 10  # 会話がこの件数で、信頼度1.0
CONFIDENT_DAYS = 3  # 歩数・すれ違いがこの日数で、信頼度1.0
MAX_STEPS = 200000
MAX_MEETS = 1000

LOGIC_WORDS = ("なぜなら", "だから", "つまり", "理由", "比べ", "比較", "たとえば", "例えば", "まず", "次に",
               "結局", "したがって", "なので", "根拠", "数字", "割合", "確率")
SENSE_WORDS = ("すごい", "楽しい", "なんか", "めっちゃ", "気がする", "やばい", "うれしい", "嬉しい", "かわいい",
               "好き", "最高", "わくわく", "ドキドキ", "感じ")
QUESTION_WORDS = ("？", "?", "どうして", "なんで", "なぜ", "どう思", "教えて", "って何", "とは", "ですか", "かな")
QUESTION_ENDINGS = ("か", "の")  # 文の終わり。音声から変換した文字には「？」が付かないことがあるので、これも見る


def is_question(text):
    text = text.strip()
    if any(w in text for w in QUESTION_WORDS):
        return True
    return text.rstrip("。.!！ 　").endswith(QUESTION_ENDINGS)


def _bigrams(text):
    text = "".join(ch for ch in text if not ch.isspace())
    return {text[i:i + 2] for i in range(len(text) - 1)} or {text}


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def _hour(turn):
    at = turn.get("at")
    return at.astimezone(JST).hour if at is not None else None


def talk_levels(turns, topic_weight=DEFAULT_TOPIC_WEIGHT):
    """会話から、{軸: (水準L, 信頼度c)}。会話がなければ空。"""
    texts = [t.get("text", "") for t in turns]
    n = len(texts)
    if n == 0:
        return {}
    conf = min(1.0, n / CONFIDENT_TALKS)
    levels = {}

    hours = [h for h in (_hour(t) for t in turns) if h is not None]
    if hours:
        night = sum(1 for h in hours if h >= 22 or h <= 4)
        levels["nightowl"] = (night / len(hours), conf)
        days = {t["at"].astimezone(JST).date() for t in turns if t.get("at") is not None}
        levels["talkative"] = (min(1.0, (n / len(days)) / TALKS_FULL), conf)

    logic = sum(text.count(w) for text in texts for w in LOGIC_WORDS)
    sense = sum(text.count(w) for text in texts for w in SENSE_WORDS)
    levels["logical"] = ((logic + 1) / (logic + sense + 2), conf)

    seen, new = [], 0
    for text in texts:
        grams = _bigrams(text)
        if not seen or max(_jaccard(grams, s) for s in seen) < 0.2:
            new += 1
        seen.append(grams)
    asked = sum(1 for text in texts if is_question(text))
    levels["curious"] = (topic_weight * (new / n) + (1 - topic_weight) * min(1.0, (asked / n) / 0.3), conf)
    logging.info("性格の材料: 会話%d件 新しい話題%.2f 質問%.2f 論理%d 感覚%d", n, new / n, asked / n, logic, sense)
    return levels


def sensor_levels(days):
    """1日分の記録(steps, meets)から、{軸: (水準L, 信頼度c)}。"""
    if not days:
        return {}
    conf = min(1.0, len(days) / CONFIDENT_DAYS)
    return {
        "activity": (min(1.0, sum(d.get("steps", 0) for d in days) / len(days) / STEPS_FULL), conf),
        "friendly": (min(1.0, sum(d.get("meets", 0) for d in days) / len(days) / MEETS_FULL), conf),
    }


def update_axes(axes, base, levels, eta, max_shift):
    """6軸を、更新式で動かす。levels にない軸は、そのまま。"""
    new = dict(axes)
    for name, (level, conf) in levels.items():
        v = axes.get(name, 0.5)
        v = v + eta * conf * (level - v)
        b = base.get(name, axes.get(name, 0.5))
        new[name] = round(min(max(v, b - max_shift), b + max_shift), 4)
        new[name] = min(max(new[name], 0.0), 1.0)
    return new


def _config(db):
    snap = db.collection("config").document("game").get()
    cfg = snap.to_dict() if snap.exists else {}

    def number(key, default, high=None):
        v = cfg.get(key)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 and (high is None or v <= high)
        return float(v) if ok else default

    return {
        "eta": number("personalityEta", DEFAULT_ETA),
        "maxShift": number("personalityMaxShift", DEFAULT_MAX_SHIFT),
        "updateEvery": max(1.0, number("personalityUpdateEvery", UPDATE_EVERY_TALKS)),
        "topicWeight": number("curiousNewTopicWeight", DEFAULT_TOPIC_WEIGHT, high=1.0),
    }


def _daily(db, pet_id, generation):
    docs = db.collection("pets").document(pet_id).collection("dailyStats").stream()
    return [d.to_dict() for d in docs if d.to_dict().get("generation") == generation]


def maybe_update_personality(db, pet_id, now, run_tx=run_in_transaction, from_progress=False):
    """更新の条件を満たしていれば、性格を更新する。失敗しても、呼んだ側は止めない。

    条件: 前回から会話が UPDATE_EVERY_TALKS 回ふえた、または、前回から24時間たって何か材料がある。
    """
    try:
        cfg = _config(db)
        claim = _claim(db, pet_id, now, run_tx, from_progress, cfg["updateEvery"])
        if claim is None:
            return {"updated": False}
        pet = claim
        generation = pet.get("generation", 1)
        levels = {**talk_levels(read_turns(db, pet_id, generation), cfg["topicWeight"]),
                  **sensor_levels(_daily(db, pet_id, generation))}
        if not levels:
            return {"updated": False}
        axes = update_axes(pet.get("personalityAxes", {}), pet.get("axesBase", {}), levels,
                           cfg["eta"], cfg["maxShift"])
        db.collection("pets").document(pet_id).update({"personalityAxes": axes})
        return {"updated": True, "personalityAxes": axes}
    except Exception as e:
        logging.error("性格の更新に失敗しました: %s: %s", type(e).__name__, str(e)[:300])
        return {"updated": False}


def _claim(db, pet_id, now, run_tx, from_progress, update_every=UPDATE_EVERY_TALKS):
    """更新してよければ、印(前回の更新時点)を進めて、ペットの情報を返す。二重に更新しない。"""

    def work(tx):
        ref = db.collection("pets").document(pet_id)
        snap = ref.get(transaction=tx)
        if not snap.exists:
            return None
        pet = snap.to_dict()
        points = pet.get("points", 0.0)
        gained = points - pet.get("axesUpdatedPoints", 0.0)
        last = pet.get("axesUpdatedAt") or pet.get("generationStartedAt") or pet.get("createdAt")
        hours = (now - last).total_seconds() / 3600 if last is not None else 0
        due = gained >= update_every or (hours >= UPDATE_AFTER_HOURS and (gained >= 1 or from_progress))
        if not due:
            return None
        marks = {"axesUpdatedPoints": points, "axesUpdatedAt": now}
        if not pet.get("axesBase"):
            marks["axesBase"] = dict(pet.get("personalityAxes", {}))
            pet["axesBase"] = marks["axesBase"]
        tx.update(ref, marks)
        return pet

    return run_tx(db, work)


def _count(value, name, limit):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
        raise ApiError("invalid-argument", f"{name} は、0〜{limit} の整数にしてください")
    return value


def record_progress(db, uid, data, now, run_tx=run_in_transaction):
    """アプリが送る、1日分の歩数とすれ違い数を保存する。同じ日は、上書きする(送り直しても同じ結果)。

    入力: deviceId、steps、meetCount、date(YYYY-MM-DD・省略すると今日)
    """
    data = data or {}
    device_id = validate_device_id(data.get("deviceId"))
    steps = _count(data.get("steps", 0), "steps", MAX_STEPS)
    meets = _count(data.get("meetCount", 0), "meetCount", MAX_MEETS)
    today = now.astimezone(JST).date()
    day = data.get("date", today.isoformat())
    try:
        parsed = today.fromisoformat(day)
    except (TypeError, ValueError):
        raise ApiError("invalid-argument", "date は YYYY-MM-DD の形にしてください")
    if parsed > today or (today - parsed).days > 7:
        raise ApiError("invalid-argument", "date は、今日から7日前までにしてください")

    device = db.collection("devices").document(device_id).get()
    if not device.exists:
        raise ApiError("not-found", f"端末 {device_id} が登録されていません")
    device = device.to_dict()
    if device.get("ownerUid") != uid:
        raise ApiError("permission-denied", "この端末は、あなたのものではありません")
    pet_id = device.get("currentPetId")
    pet = db.collection("pets").document(pet_id).get().to_dict()
    db.collection("pets").document(pet_id).collection("dailyStats").document(parsed.isoformat()).set(
        {"generation": pet.get("generation", 1), "ownerUid": uid, "steps": steps, "meets": meets,
         "updatedAt": now})
    result = maybe_update_personality(db, pet_id, now, run_tx, from_progress=True)
    return {"status": "ok", "date": parsed.isoformat(), "personalityUpdated": result["updated"]}
