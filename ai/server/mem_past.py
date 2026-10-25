"""
mem_past.py — 前の代の話：どの代を見るか・前の代の思い出（pastMemories）・旅の記録（journeys）の値を質問に合わせて並べる
"""
import re
import unicodedata
from datetime import date
from typing import Any, List, Optional, Tuple

from common import AXIS_ALIASES, PetProfile, to_date
from mem_names import unmask
from mem_text import HARD_RE, _ends_past

# ---------------------------------------------------------------- 前の代（journeys）
GREW = {"active": "元気になった", "affection": "人懐っこくなった", "talkative": "おしゃべりになった",
        "logic": "物知りになった", "curious": "好奇心いっぱいになった", "night": "夜ふかしするようになった"}
SPEECH_SKIP = {"", "標準", "standard", "none", "None"}


def target_generation(kind: str, p: PetProfile, journeys: Optional[List[Any]], past_memories: Optional[List[Any]]):
    """前の代の話で、どの代を見るか（first → いちばん小さい代、past → 今の代のひとつ前）。"""
    gens = set()
    for x in list(journeys or []) + list(past_memories or []):
        if hasattr(x, "model_dump"):
            x = x.model_dump()
        try:
            gens.add(int(float(x.get("generation"))))
        except (TypeError, ValueError, AttributeError):
            pass
    if not gens:
        return None
    if kind == "first":
        return min(gens)
    if p.generation is not None:
        before = [g for g in gens if g < p.generation]
        if before:
            return max(before)
    return max(gens)


def parse_past_memories(past_memories: Optional[List[Any]], generation: Optional[int]) -> Tuple[List[dict], int]:
    """前の代の思い出（バックエンドでぼかし済み）のうち、その代のもの。心配・つらい話は使わない。
    返り値: (使う思い出, 外した数)"""
    out, dropped = [], 0
    for i, m in enumerate(past_memories or []):
        if hasattr(m, "model_dump"):
            m = m.model_dump()
        if not isinstance(m, dict) or not str(m.get("text") or "").strip():
            continue
        try:
            g = int(float(m.get("generation")))
        except (TypeError, ValueError):
            g = None
        if generation is not None and g != generation:
            continue
        text = unmask(str(m["text"]).strip().rstrip("。"), None)   # 伏せ字が残っていてもぼかす
        if HARD_RE.search(text):                                    # 前の飼い主の心配ごと・つらい話は話さない
            dropped += 1
            continue
        out.append({"id": "past:" + str(m.get("id") or f"p{i}"), "masked": text, "text": text,
                    "date": to_date(m.get("createdAt")), "generation": g})
    out.sort(key=lambda m: m["date"] or date.min, reverse=True)
    return out, dropped


def pick_journey(journeys: Optional[List[Any]], kind: str, p: PetProfile) -> Optional[dict]:
    js = []
    for j in journeys or []:
        if hasattr(j, "model_dump"):
            j = j.model_dump()
        if isinstance(j, dict):
            try:
                g = int(float(j.get("generation")))
            except (TypeError, ValueError):
                g = None
            js.append({**j, "generation": g})
    if not js:
        return None
    js.sort(key=lambda j: (j["generation"] is None, j["generation"] or 0))
    if kind == "first":
        return js[0]
    if p.generation is not None:
        before = [j for j in js if j["generation"] is not None and j["generation"] < p.generation]
        if before:
            return before[-1]
    return js[-1]


def journey_items(j: dict, kind: str = "past", first_person: str = "ぼく", baby: bool = False) -> List[dict]:
    """旅の記録を、値ごとに {key, line（【覚えていること】の文）, say（そのまま話す文。。なし）} にする。
    伏せ字はぼかす（前の代の対応は送られてこない）。"""
    if baby:
        who = "さいしょのかいぬしさん" if kind == "first" else "まえのかいぬしさん"
    else:
        who = "最初の飼い主さん" if kind == "first" else "前の飼い主さん"
    out = []
    s = str(j.get("summary") or "").strip().rstrip("。")
    if s:
        s = unmask(s, None)
        say = f"{who}とは{s}んだ" if _ends_past(s) else f"{who}とのことは「{s}」って覚えてるよ"
        out.append({"key": "summary", "line": s, "say": say})
    tod = str(j.get("timeOfDay") or "").strip()
    if tod:
        out.append({"key": "timeOfDay", "line": f"{tod}によくお話しした", "say": f"{who}とは{tod}によくお話ししたんだ"})
    sp = str(j.get("speech") or "").strip()
    if sp not in SPEECH_SKIP:
        out.append({"key": "speech", "line": f"飼い主さんは{sp}で話しかけてくれた",
                    "say": f"{who}は{sp}で話しかけてくれたんだ"})
    words = [str(w) for w in (j.get("learnedWords") or []) if w and len(str(w)) <= 10][:2]
    if words:
        q = "「" + "」「".join(words) + "」"
        out.append({"key": "learnedWords", "line": f"{q}という言葉を教えてもらった",
                    "say": f"{who}に{q}って言葉を教えてもらったんだ"})
    trait = AXIS_ALIASES.get(str(j.get("grewTrait") or ""))
    if trait:
        out.append({"key": "grewTrait", "line": f"そのころ{GREW[trait]}",
                    "say": f"{who}のところで、{first_person}は{GREW[trait]}んだ"})
    try:
        if int(j.get("talkCount") or 0) >= 30:
            out.append({"key": "talkCount", "line": "たくさんお話しした", "say": f"{who}とはたくさんお話ししたんだ"})
    except (TypeError, ValueError):
        pass
    return out


# 質問の言葉 → 先に使う値の順（当たらなければ DEFAULT_ORDER）
QUESTION_ORDER = [
    ("person", re.compile(r"どんな人|どんなひと|どういう人|どんな飼い主|どんなかいぬし|話し方|しゃべり方|喋り方|やさし|優し|"
                          r"どんな感じ|どんなかんじ"), ["speech", "timeOfDay", "summary", "talkCount"]),
    ("words", re.compile(r"教え|おしえ|言葉|ことば|口ぐせ|くちぐせ|習っ|ならっ"), ["learnedWords", "summary", "speech"]),
    ("grew", re.compile(r"変わ|かわっ|成長|せいちょう|育っ|そだっ|性格|せいかく|どうなった"), ["grewTrait", "summary", "talkCount"]),
    ("when", re.compile(r"いつ|何時|なんじ|朝|夜|昼"), ["timeOfDay", "summary"]),
    # 「前はどこにいたの？」：前の代の思い出（できごと1件）ではなく、旅の記録のまとめで答える
    ("where", re.compile(r"どこ|どちら"), ["summary", "timeOfDay", "speech", "talkCount"]),
]
DEFAULT_ORDER = ["summary", "timeOfDay", "learnedWords", "speech", "grewTrait", "talkCount"]


def order_by_question(items: List[dict], text: str) -> Tuple[List[dict], str]:
    """質問に合う値を先頭にする（ほかの値もうしろに残す。【覚えていること】には全部書く）。返り値: (並べた items, 質問の種類)"""
    t = unicodedata.normalize("NFKC", text)
    qtype, keys = "default", DEFAULT_ORDER
    for name, rx, ks in QUESTION_ORDER:
        if rx.search(t):
            qtype, keys = name, ks + [k for k in DEFAULT_ORDER if k not in ks]
            break
    rank = {k: i for i, k in enumerate(keys)}
    return sorted(items, key=lambda it: rank.get(it["key"], len(rank))), qtype


def journey_lines(j: dict) -> List[str]:
    """旅の記録を【覚えていること】の文にする。伏せ字はぼかす（対応は送られてこない）。"""
    lines = []
    s = str(j.get("summary") or "").strip().rstrip("。")
    if s:
        lines.append(unmask(s, None))
    tod = str(j.get("timeOfDay") or "").strip()
    if tod:
        lines.append(f"{tod}によくお話しした")
    sp = str(j.get("speech") or "").strip()
    if sp not in SPEECH_SKIP:
        lines.append(f"飼い主さんは{sp}で話しかけてくれた")
    words = [str(w) for w in (j.get("learnedWords") or []) if w and len(str(w)) <= 10][:2]
    if words:
        lines.append("「" + "」「".join(words) + "」という言葉を教えてもらった")
    trait = AXIS_ALIASES.get(str(j.get("grewTrait") or ""))
    if trait:
        lines.append(f"そのころ{GREW[trait]}")
    try:
        if int(j.get("talkCount") or 0) >= 30:
            lines.append("たくさんお話しした")
    except (TypeError, ValueError):
        pass
    return lines
