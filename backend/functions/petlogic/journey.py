"""旅の記録。ペットが過ごした代ごとの、まとめ。次の飼い主との会話で、前の代の話をするのに使う。

  pets/{petId}/journeys/{代}  generation, timeOfDay, learnedWords, talkCount, summary(あとから足す)
  pets/{petId}.journeys       上と同じものの配列(会話のとき、ペットと一緒に1回で読むため)
交換が確定したあと、別の関数で動かす。まず、AIを使わない値を書き、そのあとで、要約(summary)を足す。
"""
import json
import logging
from collections import Counter
from datetime import timezone, timedelta

from .memory import ANY_PLACEHOLDER, JST, read_name_map, summarize_memories
from .store import run_in_transaction
from .talklog import read_turns

MAX_MEMORIES_FOR_SUMMARY = 100
MAX_SUMMARY_CHARS = 120

SYSTEM_B = """あなたはペット育成アプリの記録係です。ペットが前の飼い主のところで過ごした思い出の一覧から、
次の飼い主に話せる「その代でいちばんの思い出」を1〜2文にまとめます。

決まり
1. 一覧にあることだけを使う。作らない。
2. 1〜2文。主語は書かない。文の終わりは「〜した」「〜してもらった」にする（例: 「{place_1}でよく散歩した」）。
3. 伏せ字（{person_1} など）はそのまま使ってよい。本当の名前は書かない。
4. 前の飼い主がだれか分かること（学校・会社・住んでいる所・家族のこと）は書かない。
5. 楽しかったこと・よくしていたことを選ぶ。心配ごとやつらいことは選ばない。

出力（JSON だけ）
{"summary": "..."}"""


def time_of_day(turns):
    """会話した時刻で、いちばん多い時間帯(朝 5–10・昼 11–16・夕方 17–19・夜 20–4)。"""
    counts = Counter()
    for t in turns:
        at = t.get("at")
        if at is None:
            continue
        h = at.astimezone(JST).hour
        counts["朝" if 5 <= h <= 10 else "昼" if 11 <= h <= 16 else "夕方" if 17 <= h <= 19 else "夜"] += 1
    return counts.most_common(1)[0][0] if counts else None


def top_words(db, pet_id, generation, n=2):
    """その代で覚えた言葉(覚えた順に、上位n個)。"""
    words = []
    for snap in db.collection("pets").document(pet_id).collection("history").stream():
        d = snap.to_dict()
        if d.get("type") == "wordsTaught" and d.get("generation") == generation:
            words += [w for w in d.get("words", []) if w not in words]
    return words[:n]


def _write_entry(db, pet_id, entry, run_tx):
    def work(tx):
        pet_ref = db.collection("pets").document(pet_id)
        pet = pet_ref.get(transaction=tx)
        if not pet.exists:
            return
        journeys = [j for j in (pet.to_dict().get("journeys") or []) if j.get("generation") != entry["generation"]]
        journeys.append(entry)
        journeys.sort(key=lambda j: j["generation"])
        tx.update(pet_ref, {"journeys": journeys})
        tx.set(pet_ref.collection("journeys").document(str(entry["generation"])), entry)

    run_tx(db, work)


def write_journey_values(db, pet_id, generation, talk_count, run_tx=run_in_transaction):
    """AIを使わない値だけを、先に書く。"""
    entry = {"generation": generation, "learnedWords": top_words(db, pet_id, generation),
             "talkCount": int(talk_count)}
    tod = time_of_day(read_turns(db, pet_id, generation))
    if tod:
        entry["timeOfDay"] = tod
    _write_entry(db, pet_id, entry, run_tx)
    return entry


def add_journey_summary(db, pet_id, generation, ask_ai, run_tx=run_in_transaction):
    """その代の思い出を要約して、summary を足す。思い出が0件なら、何もしない。"""
    memories = [d for d in (s.to_dict() for s in db.collection("pets").document(pet_id).collection("memories").stream())
                if d.get("generation") == generation]
    if not memories:
        return {"status": "no_memories"}
    memories.sort(key=lambda d: d["createdAt"])
    lines = "\n".join(f"- {d['text']}" for d in memories[:MAX_MEMORIES_FOR_SUMMARY])
    raw = ask_ai(SYSTEM_B, f"思い出の一覧:\n{lines}")
    summary = json.loads(raw).get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return {"status": "no_summary"}
    summary = summary.strip()
    owners = {d.get("ownerUid") for d in memories}
    real_names = [v for o in owners for v in read_name_map(db, o, pet_id).values()]
    if len(summary) > MAX_SUMMARY_CHARS or any(n in summary for n in real_names):
        return {"status": "rejected"}  # 長すぎる、または本当の名前が残っている
    snap = db.collection("pets").document(pet_id).collection("journeys").document(str(generation)).get()
    entry = {**(snap.to_dict() if snap.exists else {"generation": generation}), "summary": summary}
    _write_entry(db, pet_id, entry, run_tx)
    return {"status": "done"}


def _claim_status(db, handoff_id, expect, to, run_tx):
    def work(tx):
        ref = db.collection("handoffs").document(handoff_id)
        snap = ref.get(transaction=tx)
        if not snap.exists or snap.to_dict().get("journeyStatus") != expect:
            return None
        tx.update(ref, {"journeyStatus": to})
        return snap.to_dict()

    return run_tx(db, work)


def start_journeys(db, handoff_id, run_tx=run_in_transaction):
    """① 交換の直後に、AIを使わない値を書く。"""
    handoff = _claim_status(db, handoff_id, "pending", "values", run_tx)
    if handoff is None:
        return {"status": "skipped"}
    counts = handoff.get("endedTalkCounts") or {}
    for pet_id, generation in (handoff.get("endedGenerations") or {}).items():
        try:
            write_journey_values(db, pet_id, generation, counts.get(pet_id, 0), run_tx)
        except Exception as e:
            logging.error("旅の記録(値)に失敗しました: %s: %s", type(e).__name__, str(e)[:300])
    return {"status": "values"}


def finish_journeys(db, handoff_id, ask_ai, now, run_tx=run_in_transaction):
    """② 残った会話を要約して、旅の記録に summary を足す。"""
    handoff = _claim_status(db, handoff_id, "values", "working", run_tx)
    if handoff is None:
        return {"status": "skipped"}
    failed = False
    for pet_id, generation in (handoff.get("endedGenerations") or {}).items():
        try:
            if summarize_memories(db, pet_id, generation, ask_ai, now, force=True, run_tx=run_tx)["status"] == "failed":
                failed = True
            add_journey_summary(db, pet_id, generation, ask_ai, run_tx)
        except Exception as e:
            failed = True
            logging.error("旅の記録(要約)に失敗しました: %s: %s", type(e).__name__, str(e)[:300].replace("\n", " "))
    status = "failed" if failed else "done"
    db.collection("handoffs").document(handoff_id).update({"journeyStatus": status})
    return {"status": status}
