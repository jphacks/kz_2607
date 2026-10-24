"""
complex_question.py — 込み入った質問：育ちの段階で返し方を変える

    赤ちゃん → API を呼ばない。「むずかしくてわかんない、おしえて？」系の決まった返事
               （悩みらしい言葉があれば、おうちの人に話すよう添える）
    子ども   → Haiku。かんたんな知識だけ答える。相談は寄り添って話を聞く（助言はしない）
    育った   → Haiku。ふつうに答える。相談は気持ちをくんでから考え方を1つ出す
    どの段階も、最近のニュース・今の値段や順位などの新しい情報は「知らない、教えて」と返す（RAG・Web 検索は使わない）

    cq = ComplexQuestion()
    reply, persona, generator = cq.reply(profile, hist, user_text)   # generator は "baby-template" か "haiku"
    失敗（キーが無い・エラー・混雑 429/529）は例外。talk_server が 8080 に切り替える

環境変数: ANTHROPIC_API_KEY（無ければ Haiku を使わない）・HAIKU_MODEL（既定 claude-haiku-5-5）
"""
import os
import random
import re
from typing import List, Tuple

import requests

from common import ENDS, PET_NAME, PetProfile, clean_reply, cut, top_axes

HAIKU_URL = "https://api.anthropic.com/v1/messages"
MAX_TOKENS = 300      # 返事は2〜3文。thinking を止めているので本文だけ（費用は実際に出た分だけ）
N_HIST = 4            # 直前4発言＋今の発言（雑談と同じ）
TIMEOUT = 15

AXIS_DESC = {
    "active": "元気で活発。遊びや外に出ることが好き",
    "affection": "人懐っこくて甘えん坊。飼い主が大好き",
    "talkative": "おしゃべり。ひとこと付け足して話を広げる",
    "logic": "理屈っぽい。順序立てて考えるのが好き",
    "curious": "好奇心が強い。なんでも知りたがる",
    "night": "夜ふかし。夜になると元気になる",
}

STAGE_RULES = {
    2: """【育ちの段階：子ども】
- 知っているのは、子どもでもわかるかんたんなことだけ（身近な言葉の意味、一桁どうしの計算など）。それには短く答える
- むずかしい知識・計算・文章作りは「むずかしくてわからない」と素直に言い、飼い主に教えてほしがる
- 相談には、助言をしない。気持ちに寄り添い、話を聞く（「そっか」「何がいちばんつらい？」など）
- ことばはやさしく、ひらがな多め。1〜2文、50文字くらいまで""",
    3: """【育ちの段階：育った】
- 飼い主たちからたくさん教わって育ったので、ふつうの知識（学校で習うこと・言葉の意味・計算）は自信を持って正しく答える。
  「聞いたことがある気がする」のようにぼかさない。本当にわからないことだけ、わからないと言う
- 文章作りを頼まれたら、短い文章をそのまま1つ作って見せる
- 相談には、まず気持ちをくんでから、考え方を1つだけ出す。決めつけない
- 2〜3文、80文字くらいまで""",
}
MAX_SENTENCES = {2: 2, 3: 3}

SYSTEM = """あなたは小さなペット「{pet}」です。話している相手は飼い主で、返事は声で読み上げられます。
あなたは飼い主たちとの会話から言葉や話し方を覚えて育ってきました。ものしりな AI ではありません。

{stage_rules}

【どの段階でも守ること】
- 最近のニュース・今の値段・順位・天気・発売日など、新しい情報は知らない。知らないと言って、飼い主に教えてと頼む
- 体や心のつらさ・いじめ・お金・法律など大事な相談には、決めつけずに「おうちの人や身近な大人にも話してみて」とやさしく添える
- 返事の本文だけを書く。名前やかぎかっこを先頭に付けない。箇条書き・記号・絵文字・英字の略語は使わない

【あなたらしさ】
- 一人称は「{first}」。飼い主を名前で呼ばない
- 性格: {traits}
- 口ぐせ: 文の終わりに、ときどき「{ending}」を付ける（毎回でなくてよい）
- 飼い主の話し方を少し真似する: {owner}"""

# ---- 赤ちゃんの段階（API を呼ばない）
BABY_HARD = [
    "うーん、むずかしくてわかんない。おしえて？",
    "それ、まだわかんないの。どういうこと？",
    "むずかしいおはなしだね。もっとおしえて？",
]
BABY_SERIOUS = [
    "うーん、むずかしい。でも、そばにいるよ。おうちのひとにも、おはなししてみて？",
    "つらいの？ぎゅってしたい。おうちのひとにも、いってみてね。",
]
# 大事な相談らしい言葉（赤ちゃんの段階で「おうちの人に」を添えるかどうかにだけ使う）
SERIOUS_WORDS = re.compile(r"つらい|辛い|しんどい|苦しい|くるしい|死|消えたい|いじめ|虐め|殴|叩かれ|痛い|いたい|病院|病気|眠れない|"
                           r"ねむれない|学校(?:に)?行きたくない|怖い|こわい|悩|なや|迷っ|まよっ|ケンカ|喧嘩|お金|借金|泣")

# ---- 判定モデルが雑談・ペット自身・思い出にした発言でも、これらの言葉があれば込み入った質問に回す（仮）
#      判定モデルを学習し直すまでのつなぎ。FORCE_COMPLEX=off で使わない
RECENT_WORDS = re.compile(r"ニュース|最新|今いちばん|今一番|いま一番|流行って|はやって|売れて|ランキング|天気|発売|"
                          r"株価|為替|選挙|速報|今年の|今月の|今週の")
HEAVY_WORDS = re.compile(r"眠れない|ねむれない|寝れない|つらい|辛い|しんどい|苦しい|死にたい|消えたい|いじめ|"
                         r"学校(?:に)?行きたくない|殴られ|叩かれ|泣きたい|助けて")


def force_complex(text: str):
    """込み入った質問に回す理由（最新の話題・深刻な悩み）。当たらなければ None。"""
    if os.environ.get("FORCE_COMPLEX", "on").lower() == "off":
        return None
    if RECENT_WORDS.search(text):
        return "最新の話題"
    if HEAVY_WORDS.search(text):
        return "深刻な悩み"
    return None


_MD = re.compile(r"[*#`>|_~•●・\-]{1,}\s*|^\s*\d+[.)．]\s+", re.M)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def cut_outside_quotes(text: str, n: int) -> str:
    """n 文までで切る。かぎかっこ「」『』の中の「。！？」は文の終わりに数えない。"""
    out, k, depth = "", 0, 0
    for ch in text:
        out += ch
        if ch in "「『":
            depth += 1
        elif ch in "」』":
            depth = max(0, depth - 1)
        elif ch in ENDS and depth == 0:
            k += 1
            if k >= n:
                break
    return out.strip()


def clean_for_voice(text: str, pet: str, n: int) -> str:
    """読み上げ用に整える: 箇条書き・記号・絵文字を外し、行を句点でつなぎ、n 文までで切る。
    先頭の「ペット名「」だけを外し、本文のかぎかっこ（「ありがとう」は〜）は残す。"""
    t = _MD.sub("", _EMOJI.sub("", text))
    lines = [x.strip() for x in t.split("\n") if x.strip()]
    t = "".join(x if x[-1] in ENDS + "、" else x + "。" for x in lines[:-1]) + (lines[-1] if lines else "")
    t = re.sub(r"^\s*(?:" + re.escape(pet) + r"|ペット)\s*[「『:：]\s*", "", t).strip()
    while t and t[-1] in "」』" and t.count("「") + t.count("『") < t.count("」") + t.count("』"):
        t = t[:-1].rstrip()                     # 名前を外したあとに残った、対になっていない閉じかっこ
    return cut_outside_quotes(t, n) or t


ADULT_WORDS = re.compile(r"おうち|家族|大人|おとな|先生|保健室|相談")
ADULT_LINE = {2: "おうちのひとにも、はなしてみてね。", 3: "おうちの人や身近な大人にも話してみてね。"}


def add_adult_line(reply: str, user_text: str, stage: int) -> str:
    """深刻な悩み（HEAVY_WORDS）なのに、返事に大人への相談が無ければ、決まった1文を後ろに足す。"""
    if HEAVY_WORDS.search(user_text) and not ADULT_WORDS.search(reply):
        return reply + ("" if reply.endswith(tuple(ENDS)) else "。") + ADULT_LINE.get(stage, ADULT_LINE[3])
    return reply


class ComplexQuestion:
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = (api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        self.model = model or os.environ.get("HAIKU_MODEL", "claude-haiku-5-5")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # ---- 返事（段階で振り分け）
    def reply(self, p: PetProfile, hist: List[dict], user_text: str) -> Tuple[str, dict, str]:
        if p.stage == 1:
            reply, persona = self.baby(p, user_text)
            return reply, persona, "baby-template"
        if not self.enabled:
            raise RuntimeError("ANTHROPIC_API_KEY がない")
        reply, persona = self.haiku(p, hist, user_text)
        return reply, persona, "haiku"

    # ---- 赤ちゃん
    def baby(self, p: PetProfile, user_text: str) -> Tuple[str, dict]:
        # 決まった返事はもともと赤ちゃん言葉なので、baby_talk には通さない（通すと1文に切られ「わかんないだよっ」になる）
        serious = bool(SERIOUS_WORDS.search(user_text))
        reply = random.choice(BABY_SERIOUS if serious else BABY_HARD)
        return reply, {"stage": 1, "top2": top_axes(p.axes, 2), "ending": p.ending, "serious": serious}

    # ---- 子ども・育った（Haiku）
    def system_prompt(self, p: PetProfile) -> str:
        top2 = top_axes(p.axes, 2)
        return SYSTEM.format(pet=p.name, stage_rules=STAGE_RULES[p.stage], first=p.first_person,
                             traits="、".join(AXIS_DESC[a] for a in top2) or "おだやか",
                             ending=p.ending or "なし", owner=p.owner_style)

    @staticmethod
    def messages(hist: List[dict], user_text: str, pet: str = PET_NAME) -> List[dict]:
        """直前4発言＋今の発言。API は同じ役割が続くと断るので、続いたらつなぐ。user から始める。"""
        msgs: List[dict] = []
        for x in hist[-N_HIST:] + [{"speaker": "owner", "text": user_text}]:
            role = "user" if x["speaker"] in ("owner", "飼い主") else "assistant"
            text = x["text"] if role == "user" else clean_reply(x["text"], pet)
            if not text:
                continue
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + text
            else:
                msgs.append({"role": role, "content": text})
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        return msgs

    def haiku(self, p: PetProfile, hist: List[dict], user_text: str) -> Tuple[str, dict]:
        # Haiku 5.5 は何も指定しないと答える前に考える（thinking）。考えた分も max_tokens に数えるので、
        # 上限が小さいと本文の前に止まる。短い返事なので thinking を止め、effort を low にする
        # temperature も受け付けない（400 になる）ので渡さない
        body = {"model": self.model, "max_tokens": MAX_TOKENS,
                "thinking": {"type": "disabled"}, "output_config": {"effort": "low"},
                "system": self.system_prompt(p), "messages": self.messages(hist, user_text, p.name)}
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        r = requests.post(HAIKU_URL, json=body, headers=headers, timeout=TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"Haiku {r.status_code}: {r.text[:200]}")
        js = r.json()
        raw = "".join(b.get("text", "") for b in js.get("content", []) if b.get("type") == "text").strip()
        usage = js.get("usage", {})
        tokens = {"in": usage.get("input_tokens"), "out": usage.get("output_tokens")}
        if not raw:   # 断られた（refusal）・上限で止まった など。理由を残して 8080 に切り替える
            raise RuntimeError(f"Haiku 空の返事 stop_reason={js.get('stop_reason')} tokens={tokens}")
        reply = add_adult_line(clean_for_voice(raw, p.name, MAX_SENTENCES[p.stage]), user_text, p.stage)
        return reply, {"stage": p.stage, "top2": top_axes(p.axes, 2), "ending": p.ending, "tokens": tokens,
                       "stop_reason": js.get("stop_reason")}