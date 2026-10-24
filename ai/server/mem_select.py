"""
mem_select.py — 今の飼い主との思い出（memories）から、今の発言に合うものを最大2件選ぶ
"""
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import mem_config as C
from common import to_date
from mem_embed import Embedder
from mem_kind import date_range
from mem_names import unmask

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


def select_memories(embedder: Embedder, text: str, items: List[dict], name_map: Dict[str, str],
                    today: date) -> Tuple[List[dict], dict]:
    """今の発言に合う思い出を最大2件。返り値: (選んだもの, 記録)。"""
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
