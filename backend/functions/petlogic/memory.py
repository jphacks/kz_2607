"""思い出。会話を要約して「覚えてるよ」と話すための材料にする。

  pets/{petId}/memories/{id}            ownerUid, generation, text(伏せ字入り), createdAt(できごとの日)
  pets/{petId}/memoryCache/current      今の飼い主・今の代の、最近30件 items: [{id, text, createdAt}]
  users/{uid}/nameMaps/{petId}          伏せ字 → 本当の名前。その飼い主だけが使う(次の飼い主には渡さない)
会話が10件たまるごとに、別の関数(Firestoreトリガー)で要約する。返事は待たせない。
"""
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from .store import run_in_transaction
from .talklog import claim_pending, release_claim

JST = timezone(timedelta(hours=9))
BATCH_TURNS = 10  # この件数で、要約する
MIN_TURNS = 3  # これに満たない会話は、要約しない
MAX_MEMORIES_PER_RUN = 3
CACHE_SIZE = 30
MAX_MEMORY_CHARS = 100
MAX_NAME_CHARS = 30
PLACEHOLDER = re.compile(r"^\{(person|shop|place|school|company|event|food)_\d+\}$")
ANY_PLACEHOLDER = re.compile(r"\{[a-z]+_\d+\}")

SYSTEM_A = """あなたはペット育成アプリの記録係です。飼い主とペットの会話から、あとでペットが
「うん、覚えてるよ！〜したよね。」と話せる「思い出」を作ります。

決まり
1. 思い出にするのは、飼い主が実際にしたこと・飼い主が話してくれたことだけ。
   ペットの発言の中身（ペットの体験・想像）は思い出にしない。
2. 1件は1文。主語（飼い主）は書かない。文の終わりは「〜した」「〜と話してくれた」「〜と言っていた」にする。
   「一緒に」は、ペットと一緒にしたときだけ書く。
3. 多くても3件。思い出にするほどのことが無ければ空の配列。あいさつや相づちだけの会話は思い出にしない。
4. 人・お店・場所・学校・会社・催し・商品の「固有の名前」は伏せ字にする。
   種類: person, shop, place, school, company, event, food（例: {person_1}, {shop_1}）
   - known_names にある名前は、その伏せ字を使う
   - 新しい名前は、その種類の次の番号を使い、new_names に入れる
   - 「公園」「アイス」「テスト」のような一般の言葉は伏せ字にしない
5. 次のことは思い出にしない: 病気・けが・体のこと、お金、住所・電話番号・メール、家族のもめごと、
   危ないこと、だれかの悪口。
6. occurred_on は、できごとがあった日（today を基準に「昨日」「先週の土曜」などから決める）。
   わからなければ会話の日。

出力（JSON だけ）
{"memories": [{"text": "...", "occurred_on": "YYYY-MM-DD"}], "new_names": {"{shop_1}": "ミスド"}}"""


def build_user_prompt(today, known_names, turns):
    lines = [f"today: {today}", f"known_names: {json.dumps(known_names, ensure_ascii=False)}", "会話:"]
    for t in turns:
        lines.append(f"飼い主: {t.get('text', '')}")
        lines.append(f"ペット: {t.get('reply', '')}")
    return "\n".join(lines)


def _day(value, fallback):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else fallback
    except ValueError:
        return fallback


def parse_memories(raw, known_names, today):
    """AIの返事(JSONの文字列)から、保存してよい思い出と、新しい名前を取り出す。

    本当の名前が文に残っているもの、解決できない伏せ字を含むものは、捨てる。
    """
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("JSONの形が違います")
    new_names = {}
    for key, value in (data.get("new_names") or {}).items():
        key = key if str(key).startswith("{") else "{" + str(key) + "}"
        if PLACEHOLDER.match(key) and key not in known_names and isinstance(value, str) \
                and 0 < len(value.strip()) <= MAX_NAME_CHARS:
            new_names[key] = value.strip()
    names = {**known_names, **new_names}
    real_names = [v for v in names.values() if v]
    memories = []
    for item in (data.get("memories") or [])[:MAX_MEMORIES_PER_RUN]:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_MEMORY_CHARS:
            continue
        text = text.strip()
        if any(name in text for name in real_names):
            continue  # 伏せ字にし忘れた名前
        if any(p not in names for p in ANY_PLACEHOLDER.findall(text)):
            continue  # 対応する名前がない伏せ字
        memories.append({"text": text, "occurred_on": _day(item.get("occurred_on"), today)})
    return memories, new_names


def read_name_map(db, uid, pet_id):
    if not uid:
        return {}
    snap = db.collection("users").document(uid).collection("nameMaps").document(pet_id).get()
    return dict(snap.to_dict()) if snap.exists else {}


def rebuild_cache(db, pet_id, owner_uid, generation, now):
    memories = [(s.id, s.to_dict()) for s in db.collection("pets").document(pet_id).collection("memories").stream()]
    mine = [(i, d) for i, d in memories if d.get("ownerUid") == owner_uid and d.get("generation") == generation]
    mine.sort(key=lambda x: x[1]["createdAt"], reverse=True)
    items = [{"id": i, "text": d["text"], "createdAt": d["createdAt"].isoformat()} for i, d in mine[:CACHE_SIZE]]
    db.collection("pets").document(pet_id).collection("memoryCache").document("current").set(
        {"ownerUid": owner_uid, "generation": generation, "items": items, "updatedAt": now})
    return items


def summarize_memories(db, pet_id, generation, ask_ai, now, force=False, run_tx=run_in_transaction):
    """たまった会話を要約して、思い出にする。force なら、少なくても(3件以上)要約する。"""
    claim = claim_pending(db, pet_id, generation, MIN_TURNS if force else BATCH_TURNS, run_tx)
    if claim is None:
        return {"status": "skipped"}
    owner = claim["ownerUid"]
    try:
        today = now.astimezone(JST).date()
        known = read_name_map(db, owner, pet_id)
        raw = ask_ai(SYSTEM_A, build_user_prompt(today.isoformat(), known, claim["turns"]))
        memories, new_names = parse_memories(raw, known, today)
        if new_names:
            db.collection("users").document(owner).collection("nameMaps").document(pet_id).set({**known, **new_names})
        for m in memories:
            when = datetime(m["occurred_on"].year, m["occurred_on"].month, m["occurred_on"].day, 12, tzinfo=JST)
            db.collection("pets").document(pet_id).collection("memories").document().set(
                {"ownerUid": owner, "generation": generation, "text": m["text"], "createdAt": when})
        rebuild_cache(db, pet_id, owner, generation, now)
    except Exception as e:
        logging.error("思い出の要約に失敗しました: %s: %s", type(e).__name__, str(e)[:300].replace("\n", " "))
        release_claim(db, pet_id, generation, claim["prev"], run_tx)
        return {"status": "failed"}
    return {"status": "done", "memories": len(memories)}


def load_talk_context(db, uid, pet_id, pet):
    """会話のとき、AIに付ける材料。今の飼い主・今の代の分だけ。失敗しても、空を返す。"""
    try:
        cache = db.collection("pets").document(pet_id).collection("memoryCache").document("current").get()
        memories = []
        if cache.exists:
            c = cache.to_dict()
            if c.get("ownerUid") == uid and c.get("generation") == pet.get("generation", 1):
                memories = list(c.get("items", []))
        return {"memories": memories, "nameMap": read_name_map(db, uid, pet_id),
                "journeys": list(pet.get("journeys") or [])}
    except Exception as e:
        logging.error("思い出の読み込みに失敗しました: %s: %s", type(e).__name__, str(e)[:300])
        return {}
