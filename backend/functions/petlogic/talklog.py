"""会話の記録。代ごとに、直近の会話を取っておく(交換のときの要約の材料になる)。

  pets/{petId}/talkLogs/{代}  turns: [{text, reply, at}, ...](直近 MAX_TURNS 件)
"""
import logging

from .store import run_in_transaction

MAX_TURNS = 50
MAX_CHARS = 200


def record_turn(db, pet_id, generation, text, reply, now, run_tx=run_in_transaction):
    """会話1回分を足す。失敗しても、会話は止めない。"""

    def work(tx):
        ref = db.collection("pets").document(pet_id).collection("talkLogs").document(str(generation))
        snap = ref.get(transaction=tx)
        turns = list(snap.to_dict().get("turns", [])) if snap.exists else []
        turns.append({"text": text[:MAX_CHARS], "reply": reply[:MAX_CHARS], "at": now})
        tx.set(ref, {"generation": generation, "turns": turns[-MAX_TURNS:]})

    try:
        run_tx(db, work)
    except Exception as e:
        logging.error("会話の記録に失敗しました: %s: %s", type(e).__name__, str(e)[:300])


def read_turns(db, pet_id, generation):
    """その代の会話(古い順)。なければ空。"""
    snap = db.collection("pets").document(pet_id).collection("talkLogs").document(str(generation)).get()
    return list(snap.to_dict().get("turns", [])) if snap.exists else []
