"""
mem_names.py — 伏せ字（{shop_1} など）を本当の名前に戻す・「あのお店」にぼかす
"""
import re
from typing import Any, Dict, Optional


# ---------------------------------------------------------------- 伏せ字
MASK_RE = re.compile(r"\{([A-Za-z]+)_(\d+)\}")
LEFTOVER_RE = re.compile(r"[{}｛｝]|(?:person|shop|place|school|company|event|food)_\d")
VAGUE = {"person": "あのお友だち", "shop": "あのお店", "place": "あの場所", "school": "あの学校",
         "company": "あの会社", "event": "あのイベント", "food": "あの食べもの"}


def norm_name_map(name_map: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """キーを "{shop_1}" の形にそろえる（"shop_1" でも受け取れる）。"""
    out = {}
    for k, v in (name_map or {}).items():
        if v is None or str(v).strip() == "":
            continue
        k = str(k).strip()
        if not k.startswith("{"):
            k = "{" + k + "}"
        out[k] = str(v).strip()
    return out


def unmask(text: str, name_map: Optional[Dict[str, str]] = None) -> str:
    """伏せ字を戻す。name_map にあれば本当の名前、無ければ「あのお店」などにぼかす。"""
    def rep(m):
        if name_map and m.group(0) in name_map:
            return name_map[m.group(0)]
        return VAGUE.get(m.group(1).lower(), "あれ")
    return MASK_RE.sub(rep, text or "")
