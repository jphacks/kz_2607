"""
mem_text.py — 返事の文：決まった返事（「うん、覚えてるよ！〜よね。」「覚えてないなぁ」）・一言の代わり・性格LoRA へのプロンプト
"""
import random
import re
from typing import List, Optional

from common import PetProfile, fix_reading, to_baby

# ---------------------------------------------------------------- 文の形・思い出の中身の見分け
def _ends_past(t: str) -> bool:
    return bool(re.search(r"(?:た|だ)$", t))


# 一言が使えなかったときの一言（性格によらない）。口ぐせが「あのね、〜」なら前に付ける
FALLBACK_REACT = {"good": ["楽しかったね！", "またしたいな！"],                          # 楽しい思い出
                  "hard": ["きみががんばってたの、ちゃんと知ってるよ。", "いまはどう？"],     # 心配・つらい思い出
                  "plain": ["そのときのこと、よく思い出すんだ。", "きみとのこと、大事にしてるよ。"],
                  "past": ["なつかしいなぁ。", "いまでもときどき思うんだ。"]}
HARD_RE = re.compile(r"心配|不安|悲し|つら|辛|落ち込|失敗|泣|怒|けんか|ケンカ|疲れ|忙し|しんど")
GOOD_RE = re.compile(r"食べ|行っ|見た|遊|楽し|喜|うれし|嬉し|作っ|した$|考えた|プレゼント")

def fallback_reaction(kind: str, p: PetProfile, lines: Optional[List[str]] = None) -> str:
    """一言が使えなかったときの一言。思い出が心配・つらい話なら「楽しかったね」は言わない。"""
    text = "".join(lines or [])
    if kind != "current":
        key = "past"
    elif HARD_RE.search(text):
        key = "hard"
    elif GOOD_RE.search(text):
        key = "good"
    else:
        key = "plain"
    r = random.choice(FALLBACK_REACT[key])
    if (p.ending or "").startswith("あのね"):
        r = "あのね、" + r
    return r


# ---------------------------------------------------------------- 決まった返事
DONT_KNOW = {
    "current": ["うーん、それは覚えてないなぁ。", "えっと…ちょっと思い出せないや。", "ごめんね、それは覚えてないんだ。"],
    "past": ["前のことは、あんまり覚えてないなぁ。", "うーん、前のことはよく思い出せないんだ。"],
    "only": ["{fp}は最初から、いまの飼い主さんのところにいるよ！"],
}
BABY_DONT_KNOW = {"current": ["おぼえてないの…", "んー、わかんない。"], "past": ["まえのこと、おぼえてないの。"],
                  "only": ["さいしょからここにいるの！"]}


def _baby(text: str, p: PetProfile) -> str:
    t = fix_reading(text)
    return to_baby(t, p.ending) if to_baby else t


def dont_know_reply(kind: str, p: PetProfile, only_owner: bool = False) -> str:
    k = "only" if only_owner else ("current" if kind == "current" else "past")
    if p.stage == 1:
        return random.choice(BABY_DONT_KNOW[k])
    return random.choice(DONT_KNOW[k]).format(fp=p.first_person)


def template_reply(kind: str, lines: List[str], p: PetProfile, label: str = "", says: Optional[List[str]] = None) -> str:
    """思い出の1行目だけで作る決まった返事。前の代は journey_items の say（質問に合う値が先頭）を使う。
    今の飼い主で says[0] があるのは直近の会話（まだ要約されていない発言）を引用するとき"""
    if kind == "current" and says and says[0]:
        s = says[0].rstrip("。")
        return _baby(s + "。", p) if p.stage == 1 else s + "。"
    if kind != "current" and says:
        s = says[0].rstrip("。")
        if p.stage == 1:
            return _baby(re.sub(r"[、，,！!？?「」]", "", s) + "よ。", p)
        return f"えっとね、{s}。"
    t = lines[0].rstrip("。")
    if p.stage == 1:
        # baby_talk.py は最初の一文だけ残す（「！」「、」で切れる）ので、一文・句読点なしで渡す
        b = re.sub(r"[、，,！!？?「」]", "", t)
        if kind == "current":
            return _baby(f"{label}{b}よね。" if _ends_past(b) else f"{b}のことおぼえてるよ。", p)
        who = "さいしょのかいぬしさん" if kind == "first" else "まえのかいぬしさん"
        return _baby(f"{who}とは{b}んだよ。" if _ends_past(b) else f"{who}とのこと{b}っておぼえてるよ。", p)
    if kind == "current":
        s = f"{label}{t}よね" if _ends_past(t) else f"「{t}」のこと"
        return f"うん、覚えてるよ！{s}。" if _ends_past(t) else f"うん、{s}覚えてるよ！"
    who = "最初の飼い主さん" if kind == "first" else "前の飼い主さん"
    s = f"{who}とは{t}んだ" if _ends_past(t) else f"{who}とのことは「{t}」って覚えてるよ"
    return f"えっとね、{s}。"


# ---------------------------------------------------------------- プロンプト
RULES = (
    "【答え方】いちばん大事な決まり\n"
    "- 【覚えていること】に書いてあることだけを、思い出して短く話す\n"
    "- 【覚えていること】に無い食べ物・場所・人・できごとを作らない\n"
    "- 「覚えてない」とは言わない\n"
    "- 一人称は「{fp}」"
)
RULES_PAST = "\n- 今の飼い主さんの名前や、今の飼い主さんとの思い出は話さない"
RULES_BABY = "\n- 一文で答える"


def build_extra(kind: str, lines: List[str], p: PetProfile) -> str:
    rules = RULES.format(fp=p.first_person) + (RULES_PAST if kind != "current" else "") + \
        (RULES_BABY if p.stage == 1 else "")
    head = {"current": "【覚えていること】（いまの飼い主さんとの思い出）",
            "past": "【覚えていること】（前の飼い主さんとの思い出）",
            "first": "【覚えていること】（最初の飼い主さんとの思い出）"}[kind]
    return rules + "\n\n" + head + "\n" + "\n".join(f"- {ln}" for ln in lines)


def build_rewrite_hint(sentence: str) -> str:
    """決まった返事の文をそのまま渡し、口調だけ変えさせる（何を話すかは Mac が決める）。"""
    return f"（「{sentence}」と答える。中身の言葉は変えずに、あなたの話し方で一文で言う）"


def build_hint(kind: str, lines: List[str]) -> str:
    """モデルにだけ見せるヒント（答えの中身まで書く。ペット自身の hint_ans と同じ考え）。"""
    if kind == "current":
        return f"（覚えているよと言って、「{lines[0]}」ことを、その言葉のまま最初に言う）"
    who = "最初の飼い主さん" if kind == "first" else "前の飼い主さん"
    return f"（{who}とは「{lines[0]}」と、その言葉のまま最初に言う）"


def build_react_hint(fact: str) -> str:
    return (f"（もう「{fact}」と言ったあと。あなたもそこにいたので、その思い出へのあなたの気持ちを短く一言だけ言う。"
            "例:「楽しかったね！」「またしたいな」。聞き返さない。新しいできごと・食べ物・場所・人・時間は言わない）")
