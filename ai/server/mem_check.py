"""
mem_check.py — 返事のチェック（伏せ字が残っていない・思い出の言葉を使っている・作り話をしていない など）
"""
import re
import unicodedata
from typing import List, Tuple

from common import PetProfile
from mem_embed import lexical_sim
from mem_names import LEFTOVER_RE

# ---------------------------------------------------------------- チェック
GENERIC = {"飼い主", "一緒", "思い出", "今日", "昨日", "この前", "前に", "お話", "言葉", "そのころ", "おととい",
           "あのお", "お友だち", "お店", "場所", "学校", "会社", "イベント", "食べもの"}
# 「バドミントン？」「数学のテストだったのね」「分けてもらったんだね」は、初めて聞いた話への返し方
LISTENER_RE = re.compile(r"[?？]$|(?:た|だった)(?:んだ|の)ね[。!！]?$")
DONT_KNOW_RE = re.compile(r"覚えてない|おぼえてない|覚えていない|忘れ|わすれ|わかんない|思い出せない|おもいだせない")


def key_words(lines: List[str]) -> List[str]:
    """思い出の言葉（漢字・カタカナの2文字以上、無ければひらがな3文字以上）。"""
    out = []
    for ln in lines:
        ws = re.findall(r"[一-龥々]{2,}|[ァ-ヶー]{2,}|[A-Za-z]{2,}", ln)
        ws += re.findall(r"「([^」]{1,10})」", ln)
        if not ws:
            ws = re.findall(r"[ぁ-ん]{3,}", ln)
        out += [w for w in ws if w not in GENERIC]
    return list(dict.fromkeys(out))


def split_sentences(text: str) -> List[str]:
    """「。！？!?」で文に分ける（後ろの空白は落とす）。"""
    out, cur = [], ""
    for ch in text:
        cur += ch
        if ch in "。！？!?":
            out.append(cur.strip())
            cur = ""
    if cur.strip():
        out.append(cur.strip())
    return [s for s in out if s]


def trim_to_memory(text: str, lines: List[str], max_sent: int = 2) -> str:
    """思い出の言葉が出てくる最後の文までで切る（最大 max_sent 文）。どの文にも無ければそのまま。"""
    sents = split_sentences(text)                      # 返す文はそのまま（「！」を半角にしない）
    keys = key_words(lines)
    hit = [i for i, s in enumerate(sents[:max_sent])
           if any(k in unicodedata.normalize("NFKC", s) for k in keys)]
    if not hit:
        return "".join(sents[:max_sent])
    end = hit[-1] + 1
    if len("".join(sents[:end])) < 10 and end < min(len(sents), max_sent):   # 「えっ、花火！」だけだと短いので次の文も
        end += 1
    return "".join(sents[:end])


# 気持ちの一言に出てきてよい漢字・カタカナの言葉（思い出の言葉と名前のほか）
REACT_OK_WORDS = {"一緒", "本当", "最高", "大好", "大切", "大事", "元気", "毎日", "今度", "絶対", "全部", "楽", "嬉",
                  "今日", "昨日", "思", "気持", "安心", "最初", "飼", "主", "素敵", "笑顔", "甘", "気分", "幸", "心",
                  "胸", "優", "懐", "最近"}
REACT_MAX_LEN = 30
# 一言で外すもの（10/24 の確認から）
REACT_ECHO_RE = re.compile(r"覚え|おぼえ")                                       # 「うん、覚えてるよ！」のくり返し
REACT_SKIP_RE = re.compile(r"^(?:えっ[、！!]?\s*)?(?:うん[、！!]?\s*)?(?:覚えてる|おぼえてる)よ?[！!。]?$")  # 先頭の「うん、覚えてるよ！」は飛ばす
REACT_EMPTY_RE = re.compile(r"^(?:あのね、?)?(?:えっ|うん|いいね|そっか|そうなんだ|へえ|わあ)[、！!。…]*$")  # 中身のない一言
REACT_TIME_RE = re.compile(r"きのう|昨日|今日|きょう|さっき|今朝|けさ|今は|いま、|今、")  # 時間がずれる（前の代の話で「きのうは」）
REACT_LEAD_RE = re.compile(r"^えっ[、！!]\s*")                                   # 思い出したのに驚く「えっ、」は落とす


def check_reaction(text: str, lines: List[str], names: List[str], p: PetProfile,
                   fact: str = "", facts: List[str] = ()) -> Tuple[str, List[str]]:
    """気持ちの一言（1文目）を取り出して確かめる。返り値: (一言, 外した理由)。理由があれば一言は使わない。
    facts … 今の飼い主の大事な事実の行（【いつも覚えていること】）。その言葉は一言に出てきてよい"""
    sents = [REACT_LEAD_RE.sub("", x) for x in split_sentences(text or "")]
    while sents and (not sents[0] or REACT_SKIP_RE.search(unicodedata.normalize("NFKC", sents[0]))):
        sents = sents[1:]                               # 「うん、覚えてるよ！」だけの文は飛ばして次の文を見る
    r = sents[0] if sents else ""
    reasons = []
    if not r:
        return "", ["空"]
    t = unicodedata.normalize("NFKC", r)
    if REACT_EMPTY_RE.search(t):
        reasons.append("中身がない")
    if REACT_ECHO_RE.search(t):
        reasons.append("「覚えてる」のくり返し")
    if REACT_TIME_RE.search(t):
        reasons.append("時間の言葉（作り話になりやすい）")
    if LISTENER_RE.search(t):
        reasons.append("初めて聞いた言い方（〜だったんだね）")
    if fact and lexical_sim(t, fact) >= 0.6:
        reasons.append("思い出の文のくり返し")
    if len(t) > REACT_MAX_LEN:
        reasons.append(f"長い（{len(t)}字）")
    if LEFTOVER_RE.search(t):
        reasons.append("伏せ字が残っている")
    if DONT_KNOW_RE.search(t):
        reasons.append("覚えてないと言った")
    if re.search(r"[?？]$", t) and not re.search(r"(?:ね|よ|な)[?？]$", t):
        reasons.append("聞き返している")
    allowed = "".join(lines) + "".join(facts) + "".join(names) + p.name + p.first_person
    for w in re.findall(r"[一-龥々]{2,}|[ァ-ヶー]{2,}", t):          # 思い出に無い名詞（作り話のもと）
        if w not in allowed and not any(w.startswith(k) or k in w for k in REACT_OK_WORDS):
            reasons.append(f"思い出に無い言葉「{w}」")
    return r, reasons


def memory_check(reply: str, lines: List[str], kind: str, current_names: List[str]) -> Tuple[bool, List[str]]:
    reasons = []
    t = unicodedata.normalize("NFKC", reply)
    if LEFTOVER_RE.search(t):
        reasons.append("伏せ字が残っている")
    keys = key_words(lines)
    if keys and not any(k in t for k in keys):
        reasons.append("思い出の言葉を使っていない")
    if DONT_KNOW_RE.search(t):
        reasons.append("覚えてないと言った")
    first = split_sentences(t)[0] if t.strip() else ""
    if LISTENER_RE.search(first):
        reasons.append("聞き返している（覚えていない言い方）")
    if kind != "current":
        for n in current_names:
            if len(n) >= 2 and n in t:
                reasons.append(f"前の代の話に今の飼い主の名前（{n}）")
    return (not reasons), reasons
