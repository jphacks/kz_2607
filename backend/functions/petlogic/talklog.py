"""会話の記録。代ごとに、直近の会話を取っておく(要約の材料になる)。

  pets/{petId}/talkLogs/{代}
    turns: [{seq, text, reply, at}, ...](直近 MAX_TURNS 件)
    nextSeq: 最後に付けた番号、summarizedSeq: ここまでは、思い出に要約済み
    ownerUid: その代の飼い主
"""
import logging

from .store import run_in_transaction

MAX_TURNS = 50
MAX_CHARS = 200


def _ref(db, pet_id, generation):
    return db.collection("pets").document(pet_id).collection("talkLogs").document(str(generation))


def record_turn(db, pet_id, generation, text, reply, now, run_tx=run_in_transaction, uid=None):
    """会話1回分を足す。失敗しても、会話は止めない。"""

    def work(tx):
        ref = _ref(db, pet_id, generation)
        snap = ref.get(transaction=tx)
        data = snap.to_dict() if snap.exists else {}
        seq = data.get("nextSeq", 0) + 1
        turns = list(data.get("turns", []))
        turns.append({"seq": seq, "text": text[:MAX_CHARS], "reply": reply[:MAX_CHARS], "at": now})
        tx.set(ref, {"generation": generation, "ownerUid": uid or data.get("ownerUid"),
                     "turns": turns[-MAX_TURNS:], "nextSeq": seq,
                     "summarizedSeq": data.get("summarizedSeq", 0)})

    try:
        run_tx(db, work)
    except Exception as e:
        logging.error("会話の記録に失敗しました: %s: %s", type(e).__name__, str(e)[:300])


def read_turns(db, pet_id, generation):
    """その代の会話(古い順)。なければ空。"""
    snap = _ref(db, pet_id, generation).get()
    return list(snap.to_dict().get("turns", [])) if snap.exists else []


def pending_turns(data):
    """まだ要約していない会話(番号つきのもの)。"""
    done = data.get("summarizedSeq", 0)
    return [t for t in data.get("turns", []) if isinstance(t.get("seq"), int) and t["seq"] > done]


def claim_pending(db, pet_id, generation, min_turns, run_tx=run_in_transaction):
    """要約する会話を、取り分ける(二重に要約しないよう、先に済みの印をつける)。

    min_turns 件に満たなければ None。返すのは {ownerUid, turns, prev}(prev は、戻すときの印)。
    """

    def work(tx):
        ref = _ref(db, pet_id, generation)
        snap = ref.get(transaction=tx)
        if not snap.exists:
            return None
        data = snap.to_dict()
        pending = pending_turns(data)
        if len(pending) < min_turns:
            return None
        prev = data.get("summarizedSeq", 0)
        tx.update(ref, {"summarizedSeq": pending[-1]["seq"]})
        return {"ownerUid": data.get("ownerUid"), "turns": pending, "prev": prev}

    return run_tx(db, work)


def release_claim(db, pet_id, generation, prev, run_tx=run_in_transaction):
    """要約に失敗したとき、取り分けを戻す(あとで、もう一度要約できる)。"""

    def work(tx):
        ref = _ref(db, pet_id, generation)
        snap = ref.get(transaction=tx)
        if snap.exists:
            tx.update(ref, {"summarizedSeq": min(snap.to_dict().get("summarizedSeq", 0), prev)})

    try:
        run_tx(db, work)
    except Exception as e:
        logging.error("要約の取り分けを戻せませんでした: %s: %s", type(e).__name__, str(e)[:300])
