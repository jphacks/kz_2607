"""交換のあと、手放したペットの「終わった代」の会話を要約して、取っておく(手紙の材料)。

  handoffs/{id}.summaryStatus   pending → done / failed
  pets/{petId}/summaries/{代}   summary(要約の文章)
交換の確定とは別に動く。失敗しても、交換は取り消さない。二重に動いても、結果は変わらない。
"""
import logging

from .errors import ApiError  # noqa: F401  (他のモジュールと形をそろえる)
from .llm import LlmError, openai_chat
from .store import run_in_transaction
from .talklog import read_turns

SYSTEM = (
    "あなたは、ペットと飼い主の会話を、短くまとめる係です。"
    "会話から分かる、飼い主の様子・話題・ペットとの関係を、日本語で、3文以内(200文字以内)にまとめてください。"
    "飼い主の名前や、連絡先などの個人情報は、書かないでください。会話に書かれていない事実は、足さないでください。"
)
MAX_SUMMARY_CHARS = 300


def build_prompt(pet_name, turns):
    lines = [f"ペットの名前: {pet_name or '(未設定)'}", "会話:"]
    for t in turns:
        lines.append(f"飼い主: {t.get('text', '')}")
        lines.append(f"ペット: {t.get('reply', '')}")
    return "\n".join(lines)


def make_summarizer(api_key, model, chat=openai_chat):
    def summarize(pet_name, turns):
        return chat(SYSTEM, build_prompt(pet_name, turns), api_key, model)[:MAX_SUMMARY_CHARS]

    return summarize


def summarize_handoff(db, handoff_id, summarize, now, run_tx=run_in_transaction):
    snap = db.collection("handoffs").document(handoff_id).get()
    if not snap.exists:
        return {"status": "not_found"}
    handoff = snap.to_dict()
    if handoff.get("summaryStatus") != "pending":
        return {"status": "skipped"}

    summaries, failed = {}, False
    for pet_id, generation in (handoff.get("endedGenerations") or {}).items():
        turns = read_turns(db, pet_id, generation)
        if not turns:
            continue
        pet = db.collection("pets").document(pet_id).get()
        name = pet.to_dict().get("name") if pet.exists else None
        try:
            summaries[(pet_id, generation)] = summarize(name, turns)
        except (LlmError, Exception) as e:  # 1匹の失敗で、ほかを止めない
            failed = True
            logging.error("要約に失敗しました: %s: %s", type(e).__name__, str(e)[:300].replace("\n", " "))

    def work(tx):
        ref = db.collection("handoffs").document(handoff_id)
        current = ref.get(transaction=tx)
        if not current.exists or current.to_dict().get("summaryStatus") != "pending":
            return "skipped"  # 別の実行が、先に済ませた
        for (pet_id, generation), text in summaries.items():
            doc = db.collection("pets").document(pet_id).collection("summaries").document(str(generation))
            tx.set(doc, {"generation": generation, "summary": text, "handoffId": handoff_id, "createdAt": now})
        tx.update(ref, {"summaryStatus": "failed" if failed else "done"})
        return "failed" if failed else "done"

    return {"status": run_tx(db, work), "summarized": len(summaries)}


def read_summaries(db, pet_id, generations):
    """指定した代の要約(古い順)。なければ飛ばす。"""
    out = []
    for g in sorted(generations):
        snap = db.collection("pets").document(pet_id).collection("summaries").document(str(g)).get()
        if snap.exists:
            out.append(snap.to_dict())
    return out
