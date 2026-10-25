"""
mem_select.py — 今の飼い主との思い出（memories）から、今の発言に合うものを最大2件選ぶ
"""
import re
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import mem_config as C
from common import to_date
from mem_embed import Embedder
from mem_kind import date_range
from mem_kind import is_recall
from mem_names import MASK_RE, unmask

FACT_LIKES_MAX = 3
FACT_MAX_CHARS = 30
# 事実を選ぶ質問の言葉（近さは使わない）。「きみの名前」などペット自身のことは、ペット自身・プロフィールで答えるので選ばない
FACT_ASK_RE = {"ownerName": re.compile(r"名前|なまえ|呼び方|よびかた"), "likes": re.compile(r"好き|すき|好物")}
FACT_PET_RE = re.compile(r"きみの|君の|キミの|お前の|おまえの|あなたの")
# 直近の会話（history）を思い出の候補にするとき、外す発言
RECENT_SKIP_RE = re.compile(r"^(?:ただいま|おかえり|おはよう|おやすみ|こんにちは|こんばんは|ありがとう|うん|はい|いいえ|そう|へえ|"
                            r"なるほど|ばいばい|またね|よろしく)")
# 近さが足りなくても、発言の中身の言葉（漢字・カタカナ2文字以上）が直近の発言にあれば選ぶ。日付・ふつうの言葉は数えない
KEY_RE = re.compile(r"[一-龥々]{2,}|[ァ-ヶー]{2,}|[A-Za-z]{2,}")
KEY_SKIP = {"去年", "昨日", "今日", "今週", "先週", "先月", "最近", "一緒", "思い出", "前", "飼い主", "覚え", "何時", "何処"}

# ---------------------------------------------------------------- 直近の会話（まだ要約されていない分）
def recent_items(hist: Optional[List[dict]], user_text: str, summarized_seq: Optional[int] = None) -> List[dict]:
    """受け取った直近の会話（recentTurns・history）すべてのうち、飼い主の発言を思い出の候補にする
    （ペットの発言は作り話が混ざるので使わない）。あいさつ・短い発言・質問・「覚えてる？」は外す。日付はわからないので None。
    summarized_seq … seq がこれ以下の発言は要約（memories）と重なるので外す。外すと0件になるときは外さない"""
    if not hist:
        return []
    out, seen = [], {unicodedata.normalize("NFKC", user_text).strip()}
    for i, t in enumerate(hist):
        if not isinstance(t, dict) or t.get("speaker") not in ("owner", "飼い主"):
            continue
        text = unicodedata.normalize("NFKC", str(t.get("text") or "")).strip()
        core = re.sub(r"[\s、。！？!?「」…ー〜]", "", text)
        if len(core) < 4 or text in seen or RECENT_SKIP_RE.match(core) or re.search(r"[?？]$", text) or is_recall(text):
            continue
        seen.add(text)
        quote = re.split(r"(?<=[。！!])", text)[0].strip().rstrip("。！!").strip("「」")[:30]
        out.append({"id": f"recent:{i}", "masked": quote, "text": quote, "date": None, "recent": True, "seq": t.get("seq")})
    if summarized_seq is not None:
        fresh = [m for m in out if not (isinstance(m["seq"], int) and m["seq"] <= summarized_seq)]
        if fresh:
            out = fresh
    return out


def key_hit(query: str, doc: str) -> bool:
    """今の発言の中身の言葉（日付・ふつうの言葉を除く）が、doc に1つでも入っているか。"""
    words = [w for w in KEY_RE.findall(unicodedata.normalize("NFKC", query)) if w not in KEY_SKIP]
    return any(w in doc for w in words)


# ---------------------------------------------------------------- 思い出を選ぶ
def parse_memories(memories: Optional[List[Any]], name_map: Dict[str, str]) -> List[dict]:
    out = []
    for i, m in enumerate(memories or []):
        if hasattr(m, "model_dump"):
            m = m.model_dump()
        if not isinstance(m, dict) or not str(m.get("text") or "").strip():
            continue
        masked = str(m["text"]).strip().rstrip("。")
        out.append({"id": str(m.get("id") or f"m{i}"), "masked": masked, "text": unmask(masked, name_map),
                    "date": to_date(m.get("createdAt"))})
    return out


def parse_facts(facts: Optional[Dict[str, Any]], name_map: Dict[str, str]) -> List[dict]:
    """今の飼い主の大事な事実（facts：ownerName・likes）を【いつも覚えていること】の行にする。近さでは選ばない。
    ownerName の伏せ字が nameMap に無いときは使わない（「あのお友だち」にぼかした名前で呼ばないように）"""
    out = []
    if not isinstance(facts, dict):
        return out
    name = str(facts.get("ownerName") or "").strip()
    if name and all(m.group(0) in name_map for m in MASK_RE.finditer(name)):
        real = unmask(name, name_map)[:FACT_MAX_CHARS]
        out.append({"key": "ownerName", "line": f"飼い主さんの名前は{real}", "words": [real]})
    likes = facts.get("likes")
    likes = [unmask(str(x).strip(), name_map)[:FACT_MAX_CHARS] for x in (likes if isinstance(likes, list) else [])
             if str(x or "").strip()][:FACT_LIKES_MAX]
    if likes:
        out.append({"key": "likes", "line": "飼い主さんの好きなもの：" + "・".join(likes), "words": likes})
    return out


def pick_facts(text: str, facts: List[dict]) -> List[dict]:
    """今の発言で聞かれている事実（parse_facts の中から）。「名前」→ ownerName、「好き」→ likes"""
    t = unicodedata.normalize("NFKC", text)
    if FACT_PET_RE.search(t):
        return []
    return [f for f in facts if f["key"] in FACT_ASK_RE and FACT_ASK_RE[f["key"]].search(t)]


def select_memories(embedder: Embedder, text: str, items: List[dict], name_map: Dict[str, str],
                    today: date, recent: Optional[List[dict]] = None) -> Tuple[List[dict], dict]:
    """今の発言に合う思い出を最大2件。返り値: (選んだもの, 記録)。
    recent（直近の会話）は日付でしぼらず、近さか中身の言葉で選ぶ。要約された思い出があればそちらが先。
    要約された思い出が2件そろっても、直近の会話で合うものがあれば1件は残す（要約で具体的な言葉が落ちるので）"""
    picked, info = _select_saved(embedder, text, items, name_map, today)
    recent = recent or []
    if not recent:
        return picked, info
    sims = embedder.scores(text, [(m["id"], m["text"]) for m in recent])
    order = sorted(zip(recent, sims), key=lambda x: -x[1])
    info["recent_scores"] = [(m["id"], m["text"], round(s, 3)) for m, s in order[:3]]
    hits = [m for m, s in order if s >= embedder.min_sim or key_hit(text, m["text"])]
    if hits:
        # 要約された思い出は最大 TOPK−1 件にして、直近を1件以上入れる。直近だけなら2つまで（「大学に行った」「オックスフォード大学だ」）
        picked = (picked[:C.MEMORY_TOPK - 1] + hits)[:C.MEMORY_TOPK] if picked else hits[:2]
        info.pop("why", None)
        info["picked"] = [m["id"] for m in picked]
    return picked, info


def _select_saved(embedder: Embedder, text: str, items: List[dict], name_map: Dict[str, str],
                  today: date) -> Tuple[List[dict], dict]:
    """要約された思い出（memories）から最大2件。"""
    start, end, strict, word = date_range(text, today)
    info = {"date": word, "n": len(items), "method": embedder.kind}
    cands = items
    if start is not None:
        inr = [m for m in items if m["date"] and start <= m["date"] <= end]
        info["in_range"] = len(inr)
        if strict:
            cands = inr
        elif inr:
            cands = inr
    if not cands:
        info["why"] = "その日の思い出がない" if items else "思い出がない"
        return [], info
    # 近さは全件で出す（ふだんの近さ＝中央値を知るため）。選ぶのは cands の中から
    all_sims = embedder.scores(text, [(m["id"], m["text"]) for m in items])
    sim_of = {m["id"]: s for m, s in zip(items, all_sims)}
    info["method"] = embedder.kind
    order = sorted(((m, sim_of[m["id"]]) for m in cands), key=lambda x: -x[1])
    info["scores"] = [(m["id"], round(s, 3)) for m, s in order[:3]]
    th = embedder.min_sim
    # Ruri は関係ない文どうしでも 0.8 前後になるので、ほかの思い出より抜けているか（lift）も見る。
    # 思い出が少ないと中央値があてにならないので、C.MEMORY_LIFT_MIN_N 件以上のときだけ
    use_lift = embedder.kind != "lexical" and len(items) >= C.MEMORY_LIFT_MIN_N
    base = sorted(all_sims)[len(all_sims) // 2] if all_sims else 0.0
    info["median"] = round(base, 3)

    def passes(s: float) -> bool:
        return s >= th and (not use_lift or s - base >= C.MEMORY_MIN_LIFT)

    t = unicodedata.normalize("NFKC", text)
    names = [n for n in name_map.values() if len(n) >= 2 and n in t]
    picked, top = [], order[0][1]
    for m, s in order:
        hit_name = any(n in m["text"] for n in names)
        if not picked:
            ok = passes(s) or hit_name or strict          # 日付できっちりしぼれたら1位は近さが低くても使う
        else:
            ok = hit_name or (passes(s) and top - s <= C.MEMORY_SECOND_GAP)   # 2件目は1位とほぼ同じ近さのときだけ
        if ok:
            picked.append(m)
        if len(picked) >= C.MEMORY_TOPK:
            break
    if names and picked:                       # 名前を聞かれたら、その名前が入っている思い出を先に
        picked.sort(key=lambda m: not any(n in m["text"] for n in names))
    if not picked:
        why = f"1位 {top:.3f}"
        why += f"（下限 {th}）" if top < th else ""
        if use_lift:
            why += f"・ふだんとの差 {top - base:.3f}（下限 {C.MEMORY_MIN_LIFT}）"
        info["why"] = "近さが足りない（" + why + "）"
    info["picked"] = [m["id"] for m in picked]
    return picked, info
