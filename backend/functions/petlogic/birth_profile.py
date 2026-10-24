"""誕生プロフィール(名前の候補・紹介・一人称・最初のひとこと)を、AIで作る。

  pets/{petId}.birthProfile  {nameCandidates, description, firstPerson, speechNote, firstWords, source,
                              generatedAt, regenerateCount}
  source: "ai"(OpenAIで作った) / "template"(AIが失敗したので、固定の文)
性格(personalityAxes・birthTrait)は、setInitialPersonality が保存した値を読む。アプリからは受け取らない。
"""
import json
import logging

from .birth import birth_status_of, public_profile
from .errors import ApiError
from .naming import clean_name
from .register import AXIS_NAMES
from .store import run_in_transaction
from .talk import ai_axes

FIRST_PERSONS = ("ぼく", "わたし", "おれ", "うち")
MAX_DESCRIPTION = 80
MAX_SPEECH_NOTE = 60
MAX_FIRST_WORDS = 80
AI_TIMEOUT_SEC = 12  # アプリは20秒で待ちきるので、それより短く

TEMPLATES = {
    "active": (["モチ", "ポポ", "ルル"], "元気いっぱいで、じっとしていられない子。", "ぼく", "元気な話し方。",
               "はじめまして！あえて、うれしいよっ！"),
    "affection": (["ココ", "ミミ", "ポコ"], "人なつっこくて、あまえんぼうな子。", "ぼく", "やさしい話し方。",
                  "はじめまして。そばにいてもいい？"),
    "talkative": (["ペチ", "ルン", "ポル"], "おしゃべりが大好きな子。", "わたし", "よくしゃべる話し方。",
                  "はじめまして！いっぱいお話ししようね！"),
    "logic": (["ノノ", "リオ", "テト"], "かしこくて、ものごとを考えるのが好きな子。", "ぼく", "落ち着いた話し方。",
              "はじめまして。いろいろ教えてね。"),
    "curious": (["ピコ", "ミル", "ラン"], "なんでも知りたがる、好奇心いっぱいの子。", "わたし", "わくわくした話し方。",
                "はじめまして！あれはなに？これはなに？"),
    "night": (["ルナ", "ヨル", "ホシ"], "夜ふかしが好きな、マイペースな子。", "わたし", "のんびりした話し方。",
              "はじめまして……ふあぁ、よろしくね。"),
}

SYSTEM = """あなたはペット育成アプリの、誕生の担当です。生まれたばかりのペットの「プロフィール」を作ります。
入力は、ペットの性格(6つの軸。0〜1で、0.5が中間)と、いちばん強い軸です。

決まり
1. nameCandidates: 名前の候補を3つ。1〜6文字のひらがな・カタカナ。かわいくて呼びやすい。実在の人名・商品名・悪い言葉は使わない。
2. description: 性格が伝わる紹介を1文(40文字以内)。
3. firstPerson: 一人称。「ぼく」「わたし」「おれ」「うち」のどれか1つ。
4. speechNote: 話し方のメモを1文(30文字以内)。
5. firstWords: 生まれて最初のひとこと(40文字以内)。やさしく、子どもにも安心な言葉だけ。
6. 性別・年齢・体のこと・家族のことは書かない。

出力(JSONだけ)
{"nameCandidates": ["...", "...", "..."], "description": "...", "firstPerson": "ぼく", "speechNote": "...", "firstWords": "..."}"""


def template_profile(trait):
    names, description, person, note, words = TEMPLATES.get(trait, TEMPLATES["active"])
    return {"nameCandidates": list(names), "description": description, "firstPerson": person,
            "speechNote": note, "firstWords": words, "source": "template"}


def parse_profile(raw):
    """AIの返事を確かめる。だめなら ValueError。"""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("JSONの形が違います")
    names = data.get("nameCandidates")
    if not isinstance(names, list) or len(names) != 3:
        raise ValueError("nameCandidates は3つにしてください")
    cleaned = []
    for n in names:
        try:
            cleaned.append(clean_name(n))
        except ApiError:
            raise ValueError("名前の候補に、使えないものがあります")
    if len(set(cleaned)) != 3:
        raise ValueError("名前の候補が重なっています")
    person = data.get("firstPerson")
    if person not in FIRST_PERSONS:
        raise ValueError("firstPerson が決まりの外です")
    out = {"nameCandidates": cleaned, "firstPerson": person}
    for key, limit in (("description", MAX_DESCRIPTION), ("speechNote", MAX_SPEECH_NOTE),
                       ("firstWords", MAX_FIRST_WORDS)):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError(f"{key} が空か、長すぎます")
        out[key] = value.strip()
    return {**out, "source": "ai"}


def make_profile(pet, ask_ai):
    axes = ai_axes(pet.get("personalityAxes"))
    trait = pet.get("birthTrait") or "active"
    try:
        raw = ask_ai(SYSTEM, json.dumps({"personalityAxes": axes, "strongestAxis": trait}, ensure_ascii=False))
        return parse_profile(raw)
    except Exception as e:  # AIが落ちても、誕生は止めない
        logging.error("誕生プロフィールのAI生成に失敗しました。固定の文にします: %s: %s", type(e).__name__,
                      str(e)[:200].replace("\n", " "))
        return template_profile(trait)


def generate_birth_profile(db, uid, data, now, ask_ai, run_tx=run_in_transaction):
    """入力: petId、regenerate(省略時は false)。

    作れるのは、そのペットを作った本人が、いまも持っていて、交換前の1代目で、性格を決めたあと、
    まだ生まれていない(名前をつけていない)とき。保存済みなら、false の呼び出しは、それをそのまま返す。
    """
    data = data or {}
    pet_id = data.get("petId")
    if not isinstance(pet_id, str) or not pet_id.strip():
        raise ApiError("invalid-argument", "petId を指定してください")
    regenerate = data.get("regenerate", False)
    if not isinstance(regenerate, bool):
        raise ApiError("invalid-argument", "regenerate は true / false にしてください")

    def check(pet):
        if pet.get("creatorUid") != uid or pet.get("ownerUid") != uid:
            raise ApiError("permission-denied", "このペットは、あなたのものではありません", "not_creator")
        if pet.get("generation", 1) != 1:
            raise ApiError("failed-precondition", "誕生のときだけ作れます", "birth_not_allowed")
        status = birth_status_of(pet)
        if status == "egg":
            raise ApiError("failed-precondition", "先に、性格を決めてください", "personality_not_set")
        if status == "born":
            raise ApiError("failed-precondition", "もう生まれています", "already_born")
        return status

    pet_ref = db.collection("pets").document(pet_id)
    snap = pet_ref.get()
    if not snap.exists:
        raise ApiError("not-found", "ペットが見つかりません")
    pet = snap.to_dict()
    status = check(pet)
    if status == "profile_ready" and pet.get("birthProfile") and not regenerate:
        return {"status": "ok", "petId": pet_id, "birthStatus": status, "regenerated": False,
                **public_profile(pet["birthProfile"])}

    profile = make_profile(pet, ask_ai)  # 数秒かかる。トランザクションの外で

    def work(tx):
        cur = pet_ref.get(transaction=tx).to_dict()
        cur_status = check(cur)
        old = cur.get("birthProfile")
        if old and cur_status == "profile_ready" and not regenerate:
            return {"birthStatus": cur_status, "regenerated": False, **public_profile(old)}  # 先に別の呼び出しが作った
        count = int((old or {}).get("regenerateCount", 0)) + (1 if old else 0)
        tx.update(pet_ref, {"birthProfile": {**profile, "generatedAt": now, "regenerateCount": count},
                            "birthStatus": "profile_ready"})
        return {"birthStatus": "profile_ready", "regenerated": bool(old), **public_profile(profile)}

    return {"status": "ok", "petId": pet_id, **run_tx(db, work)}
