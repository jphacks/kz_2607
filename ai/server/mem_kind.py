"""
mem_kind.py — どちらの思い出を聞いているか（今の飼い主・前の飼い主・最初の飼い主）と、日付の言葉（昨日・先週…）
"""
import re
import unicodedata
from datetime import date, timedelta
from typing import Optional, Tuple


# ---------------------------------------------------------------- どちらの思い出か
FIRST_RE = re.compile(r"(?:最初|さいしょ|一番はじめ|いちばんはじめ)の(?:飼い主|かいぬし|人|ひと|おうち|家)"
                      r"|(?:最初|さいしょ)は(?:どこ|誰|だれ)|一番最初|いちばんさいしょ")
PAST_RE = re.compile(r"前の(?:飼い主|かいぬし|人|ひと|おうち|家|代)|まえの(?:飼い主|かいぬし|ひと|おうち)"
                     r"|(?<!この)(?<!その)(?<!名)(?<!お)前は|(?<!この)(?<!その)(?<!な)(?<!お)まえは"   # 「お前は」「名前は」は除く
                     r"|前にいた|まえにいた|どこにいた|前どこ|昔の飼い主|むかしのかいぬし")
# 判定が雑談にしても思い出に回す言葉（仮）。「覚えてね」「覚えといて」は頼まれごとなので外す
RECALL_RE = re.compile(r"覚えてる|おぼえてる|覚えてない|おぼえてない|覚えている|思い出|おもいで|思いだ|(?:た|だ|してた|った)っけ"
                       r"|前の飼い主|まえのかいぬし|最初の飼い主|さいしょのかいぬし|前はどこ|前にいた|どこにいた")
NOT_RECALL_RE = re.compile(r"覚えてね|覚えておいて|覚えといて|おぼえてね|おぼえといて")


def memory_kind(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    if FIRST_RE.search(t):
        return "first"
    if PAST_RE.search(t):
        return "past"
    return "current"


def is_recall(text: str) -> Optional[str]:
    """判定の取りこぼし用。思い出を聞いていそうなら当たった言葉を返す。"""
    t = unicodedata.normalize("NFKC", text)
    if NOT_RECALL_RE.search(t):
        return None
    m = RECALL_RE.search(t)
    return m.group(0) if m else None


def is_time_question(text: str) -> bool:
    """時間を聞く質問（「昨日なにしたっけ？」「この前なにしたっけ？」）か。日付の言葉があり、思い出を聞いている。
    kind は current のまま。memory.py で前の代の思い出も候補に入れる"""
    return date_range(text, date.today())[3] is not None and bool(is_recall(text))


# ---------------------------------------------------------------- 日付のしぼり込み（日本時間の今日が基準）
def date_range(text: str, today: date) -> Tuple[Optional[date], Optional[date], bool, Optional[str]]:
    """返り値: (はじめ, おわり, きっちりしぼるか, 当たった言葉)。きっちり＝その日に無ければ「覚えてない」。"""
    t = unicodedata.normalize("NFKC", text)
    monday = today - timedelta(days=today.weekday())
    if re.search(r"おととい|一昨日", t):
        d = today - timedelta(days=2)
        return d, d, True, "おととい"
    if re.search(r"昨日|きのう|昨夜|ゆうべ|昨晩", t):
        d = today - timedelta(days=1)
        return d, d, True, "昨日"
    if re.search(r"今日|きょう|今朝|けさ", t):
        return today, today, True, "今日"
    if re.search(r"先週|せんしゅう", t):
        return monday - timedelta(days=7), monday - timedelta(days=1), True, "先週"
    if re.search(r"今週|こんしゅう", t):
        return monday, today, True, "今週"
    if re.search(r"先月|せんげつ", t):
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last, True, "先月"
    if re.search(r"去年|きょねん", t):
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), True, "去年"
    if re.search(r"最近|さいきん|この前|このまえ|こないだ|この間|このあいだ", t):
        return today - timedelta(days=7), today, False, "最近"
    return None, None, False, None


def day_label(d: Optional[date], today: date) -> str:
    """【覚えていること】に書く日付（数字はなるべく出さない）。"""
    if d is None:
        return ""
    n = (today - d).days
    return {0: "今日", 1: "昨日", 2: "おととい"}.get(n, "この前" if 0 < n <= 7 else "前に" if n > 7 else "")
