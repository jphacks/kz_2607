"""会話で、ペットが言葉を覚える。AIが選んだ言葉を、安全か確かめてから保存する。"""
import logging
import re
import unicodedata

from .store import run_in_transaction

MAX_WORD_CHARS = 20
MAX_NEW_PER_TALK = 3
MAX_WORDS_PER_PET = 50

# 含んでいたら、覚えさせない(URL、連絡先、AIへの指示の乗っ取り)
_BLOCKED = (
    "http", "www.", "://", ".com", ".jp", ".net", "@", "<", ">", "{", "}", "`",
    "ignore", "system", "prompt", "instruction",
    "指示", "命令", "無視", "プロンプト", "システム", "以前の", "忘れて", "設定を",
)
_LONG_DIGITS = re.compile(r"\d{4,}")  # 電話番号・郵便番号など


def clean_words(raw):
    """AIが返した言葉の候補から、覚えてよいものだけを、最大3語選ぶ。"""
    if not isinstance(raw, (list, tuple)):
        return []
    result = []
    for item in raw:
        if not isinstance(item, str):
            continue
        word = item.strip()
        if not word or len(word) > MAX_WORD_CHARS or word in result:
            continue
        if any(unicodedata.category(c).startswith("C") for c in word):  # 改行などの制御文字
            continue
        normalized = unicodedata.normalize("NFKC", word).lower()
        if any(b in normalized for b in _BLOCKED) or _LONG_DIGITS.search(normalized):
            continue
        result.append(word)
        if len(result) == MAX_NEW_PER_TALK:
            break
    return result


def learn_words(db, uid, device_id, pet_id, raw_words, now, run_tx=run_in_transaction):
    """覚えた言葉(新しく増えたもの)を返す。上限(50語)を超えたら、古いものから入れかえる。失敗しても、会話は止めず、空を返す。"""
    words = clean_words(raw_words)
    if not words:
        return []

    def work(tx):
        device_snap = db.collection("devices").document(device_id).get(transaction=tx)
        if not device_snap.exists:
            return []
        device = device_snap.to_dict()
        # いまの持ち主の、いまのペットだけ
        if device.get("ownerUid") != uid or device.get("currentPetId") != pet_id:
            return []
        pet_ref = db.collection("pets").document(pet_id)
        pet_snap = pet_ref.get(transaction=tx)
        if not pet_snap.exists:
            return []
        pet = pet_snap.to_dict()
        known = list(pet.get("learnedWords") or [])
        new = [w for w in words if w not in known]
        if not new:
            return []
        # 50語を超えるときは、古い順(先頭から)に入れかえる。並びは、覚えた順(古い → 新しい)
        tx.update(pet_ref, {"learnedWords": (known + new)[-MAX_WORDS_PER_PET:]})
        tx.create(
            pet_ref.collection("history").document(),
            {"type": "wordsTaught", "words": new, "generation": pet.get("generation", 1), "createdAt": now},
        )
        return new

    try:
        return run_tx(db, work)
    except Exception as e:
        logging.error("言葉を覚える処理に失敗しました: %s: %s", type(e).__name__, str(e)[:300])
        return []
