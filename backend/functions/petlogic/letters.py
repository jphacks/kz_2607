"""手紙。手放したペットが、最初に作った飼い主へ、他の人のもとでの暮らしを書く。

  pets/{petId}/letters/{日付(日本時間)}  title, body, generation, recipientUid, source, notified, createdAt
  users/{uid}/createdPets/{petId}        自分が最初に作ったペットの一覧
本文は、終わった代の要約(summaries)をもとに OpenAI が書く。失敗したら、定型の文にする。
"""
import logging
from datetime import datetime, timedelta, timezone

from .llm import openai_chat
from .store import run_in_transaction
from .summary import read_summaries
from .users import ensure_first_pet_quietly, oldest_created_pet

JST = timezone(timedelta(hours=9))
DEFAULT_INTERVAL_DAYS = 14
MAX_SUMMARIES = 3
MAX_BODY_CHARS = 800

SYSTEM = (
    "あなたは、手放されたあと、他の人のもとで暮らしているペットです。"
    "あなたを最初に育ててくれた飼い主へ、近況を伝える手紙を、あなた自身の言葉(一人称)で、日本語で書いてください。"
    "300文字以内。やさしく、あたたかい口調で。手紙の本文だけを出力してください。"
    "いまの飼い主の名前や、連絡先、細かい場所などの、個人の情報は書かないでください。"
    "渡された「最近の様子」に書かれていない出来事は、作らないでください。"
)


def interval_days(db):
    """手紙の間隔(日)。config/game の letterIntervalDays。0 にすると、すぐ出る(デモ用)。"""
    snap = db.collection("config").document("game").get()
    value = snap.to_dict().get("letterIntervalDays") if snap.exists else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return value
    return DEFAULT_INTERVAL_DAYS


def is_due(pet, now, days):
    if pet.get("generation", 1) <= 1:
        return False  # まだ誰にも手放されていない
    creator, owner = pet.get("creatorUid"), pet.get("ownerUid")
    if not creator or not owner or creator == owner:
        return False  # 作った人の手元にいる
    starts = [t for t in (pet.get("lastLetterAt"), pet.get("generationStartedAt")) if t is not None]
    if not starts:
        return False
    return now - max(starts) >= timedelta(days=days)


def build_prompt(pet, summaries):
    lines = [f"あなたの名前: {pet.get('name') or '(まだ名前がありません)'}"]
    words = (pet.get("learnedWords") or [])[:10]
    if words:
        lines.append("覚えた言葉: " + "、".join(words))
    lines.append("最近の様子:")
    if summaries:
        lines += [f"- {s['summary']}" for s in summaries]
    else:
        lines.append("- (特に記録はありません。元気に暮らしている、とだけ伝えてください)")
    return "\n".join(lines)


def template_body(pet):
    name = pet.get("name") or "わたし"
    words = (pet.get("learnedWords") or [])[:3]
    extra = f"「{'」「'.join(words)}」って言葉も、覚えたよ。" if words else ""
    return f"元気にしているよ。いまは、新しい人のもとで暮らしているんだ。{extra}\nまた会えるのを、楽しみにしているね。\n{name}より"


def write_letter(pet, summaries, chat):
    """(題, 本文, 作り方) を返す。"""
    title = f"{pet.get('name') or 'あなたのペット'}から手紙が届きました"
    try:
        return title, chat(SYSTEM, build_prompt(pet, summaries))[:MAX_BODY_CHARS], "ai"
    except Exception as e:
        logging.error("手紙の文章を作れませんでした: %s: %s", type(e).__name__, str(e)[:300].replace("\n", " "))
        return title, template_body(pet), "template"


def generate_letters(db, now, chat, notify, run_tx=run_in_transaction):
    """条件を満たしたペットの手紙を作って、通知する。1匹の失敗で、ほかを止めない。"""
    days = interval_days(db)
    made = 0
    for snap in list(db.collection("pets").stream()):
        pet_id, pet = snap.id, snap.to_dict()
        try:
            if not is_due(pet, now, days):
                continue
            generation = pet.get("generation", 1)
            ended = range(2, generation)  # 作った人の手を離れてから、終わった代
            summaries = read_summaries(db, pet_id, ended)[-MAX_SUMMARIES:]
            title, body, source = write_letter(pet, summaries, chat)
            letter_id = now.astimezone(JST).strftime("%Y-%m-%d")

            def work(tx):
                pet_ref = db.collection("pets").document(pet_id)
                ref = pet_ref.collection("letters").document(letter_id)
                if ref.get(transaction=tx).exists:
                    return False  # 同じ日に、二重には作らない
                tx.set(ref, {"title": title, "body": body, "generation": generation,
                             "recipientUid": pet["creatorUid"], "source": source,
                             "notified": False, "createdAt": now})
                tx.update(pet_ref, {"lastLetterAt": now})
                return True

            if not run_tx(db, work):
                continue
            made += 1
            try:
                ok = notify(pet["creatorUid"], title, {"type": "letter", "petId": pet_id, "letterId": letter_id})
                if ok:
                    db.collection("pets").document(pet_id).collection("letters").document(letter_id).update(
                        {"notified": True})
            except Exception as e:
                logging.error("手紙の通知に失敗しました: %s: %s", type(e).__name__, str(e)[:300])
        except Exception as e:
            logging.error("手紙の処理に失敗しました(%s): %s: %s", pet_id, type(e).__name__, str(e)[:300])
    return {"made": made}


def get_letters(db, uid, limit=30, now=None):
    """一番最初に作ったペット1体の、自分宛ての手紙を、新しい順に(最大30通)返す。

    返す: {"firstPetId": ペットのID(いなければ null), "letters": [...]}
    """
    pet_id = ensure_first_pet_quietly(db, uid, now or datetime.now(timezone.utc)) or oldest_created_pet(db, uid)
    if pet_id is None:
        return {"firstPetId": None, "letters": []}
    pet = db.collection("pets").document(pet_id).get()
    name = pet.to_dict().get("name") if pet.exists else None
    out = []
    for letter in db.collection("pets").document(pet_id).collection("letters").stream():
        d = letter.to_dict()
        if d.get("recipientUid") != uid:
            continue
        at = d.get("createdAt")
        out.append({"letterId": letter.id, "petId": pet_id, "petName": name, "title": d.get("title"),
                    "body": d.get("body"), "generation": d.get("generation"),
                    "createdAt": at.isoformat() if hasattr(at, "isoformat") else None})
    out.sort(key=lambda x: x["createdAt"] or "", reverse=True)
    return {"firstPetId": pet_id, "letters": out[:limit]}
