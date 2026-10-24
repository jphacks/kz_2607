"""
memory.py — 思い出の返事（判定が「思い出」、またはペット自身の「前のこと」）

語り方はペット自身と同じ「何を話すかは Mac が決め、性格LoRA は口調だけ」。学習はしない。
    mt = MemoryTalk(chat)                    # chat = ChatLoRA
    mt.embedder.attach(judge.runner)         # 判定モデルの Ruri を使い回す（できなければ自分で読む）
    reply, generator, persona = mt.reply(profile, hist, user_text, memories, name_map, journeys)
    persona["memory"] = {"kind", "picked", "scores", "date", "check", "reasons", ...}

流れ
  1. どちらの思い出か（memory_kind）
       first   … 最初の飼い主（journeys の一番小さい generation）
       past    … 前の飼い主・前はどこ（今の代のひとつ前）
       current … それ以外（今の飼い主との memories）
  2. 今の飼い主：Ruri で今の発言に近い思い出を最大2件。「昨日」「先週」などがあれば日本時間の日付でしぼる
  3. 無い・近さが足りない → モデルを呼ばず「覚えてないなぁ」
  4. ある → 伏せ字を戻して（今の飼い主は本当の名前、前の代は「あのお店」などにぼかす）【覚えていること】に書き、
     今の発言に答えのヒントを付けて性格LoRA（温度 MEMORY_TEMP）で言わせる
  5. チェック（伏せ字が残っていない・思い出の言葉を使っている・「覚えてない」と言っていない・
     前の代の話に今の飼い主の名前が出ていない）→ 外れたら決まった返事

/talk で受け取るもの（どれも省略可）
    memories : [{"id": "m1", "text": "{shop_1}でいちごのアイスを食べた", "createdAt": "2026-10-23T19:00:00+09:00"}]
    nameMap  : {"{shop_1}": "ミスド", "{person_1}": "ゆうと"}   … キーは "shop_1" でもよい
    journeys : [{"generation": 1, "summary": "{place_1}でよく散歩した", "timeOfDay": "夜", "speech": "関西弁",
                 "learnedWords": ["めっちゃ"], "grewTrait": "talkative", "talkCount": 45}]

環境変数:
    MEMORY_MIN_SIM … Ruri の近さの下限（初期値 0.75。check_memory.py --scores-only で決める）
    MEMORY_MIN_LEX … Ruri が読めないとき（文字の重なり）の下限（初期値 0.3）
    MEMORY_TEMP    … 温度（初期値 0.3）
    MEMORY_RURI    … auto（判定の Ruri → 自分で読む → 文字の重なり）・judge・own・lexical
    RURI_MODEL     … 自分で読むときのモデル（初期値 cl-nagoya/ruri-v3-130m）
"""
import os
import random
import threading
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from common import AXIS_ALIASES, TZ, PetProfile, fix_reading, norm, to_baby, to_date

MEMORY_MIN_SIM = float(os.environ.get("MEMORY_MIN_SIM", "0.75"))
MEMORY_MIN_LEX = float(os.environ.get("MEMORY_MIN_LEX", "0.3"))
MEMORY_TEMP = float(os.environ.get("MEMORY_TEMP", "0.3"))
MEMORY_RURI = os.environ.get("MEMORY_RURI", "auto").lower()
RURI_MODEL = os.environ.get("RURI_MODEL", "cl-nagoya/ruri-v3-130m")
MEMORY_TOPK = 2
Q_PREFIX, D_PREFIX = "検索クエリ: ", "検索文書: "


# ---------------------------------------------------------------- どちらの思い出か
FIRST_RE = re.compile(r"(?:最初|さいしょ|一番はじめ|いちばんはじめ)の(?:飼い主|かいぬし|人|ひと|おうち|家)"
                      r"|(?:最初|さいしょ)は(?:どこ|誰|だれ)|一番最初|いちばんさいしょ")
PAST_RE = re.compile(r"前の(?:飼い主|かいぬし|人|ひと|おうち|家|代)|まえの(?:飼い主|かいぬし|ひと|おうち)"
                     r"|(?<!この)(?<!その)前は|(?<!この)まえは|前にいた|まえにいた|どこにいた|前どこ|昔の飼い主|むかしのかいぬし")
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


# ---------------------------------------------------------------- 近さ（Ruri v3 → 文字の重なり）
FILLER_RE = re.compile(r"覚えてる|おぼえてる|覚えて|思い出|おもいで|っけ|のこと|ことって|って|なに|何|なん|した|してた|"
                       r"一緒に|いっしょに|話|はなし|ねえ|ね|よね|かな|[？?！!。、\s]")


def _bigrams(s: str) -> set:
    s = re.sub(r"[\s、。！？!?「」『』]", "", norm(s))
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else ({s} if s else set())


def lexical_sim(query: str, doc: str) -> float:
    """今の発言（よくある言葉を除く）の2文字の組が、思い出にどれだけ入っているか（0〜1）。"""
    q = _bigrams(FILLER_RE.sub("", unicodedata.normalize("NFKC", query)))
    if not q:
        return 0.0
    return len(q & _bigrams(doc)) / len(q)


class Embedder:
    """Ruri v3 で文をベクトルにする。思い出のベクトルは id＋text をキーにメモリ上だけで持つ（DB には保存しない）。"""

    def __init__(self, model_name: str = RURI_MODEL, mode: str = MEMORY_RURI):
        self.model_name, self.mode = model_name, mode
        self.kind = None            # "judge"・"own-st"・"own-hf"・"lexical"
        self.st = self.tok = self.model = None
        self.cache: Dict[Tuple[str, str], Any] = {}
        self.status = "未読み込み"
        self.lock = threading.Lock()   # 同時に来たとき、Ruri（判定と共有のことも）とキャッシュを1件ずつ使う

    # ---- 判定モデルの Ruri を使い回す
    def attach(self, runner) -> bool:
        if self.mode not in ("auto", "judge") or runner is None:
            return False
        cands = [runner] + [getattr(runner, n, None) for n in
                            ("encoder", "ruri", "enc", "embedder", "text_encoder", "ruri_encoder")]
        for obj in cands:
            if obj is None:
                continue
            tok = getattr(obj, "tokenizer", None) or getattr(obj, "tok", None)
            model = getattr(obj, "model", None) or getattr(obj, "backbone", None) or getattr(obj, "encoder", None)
            if tok is not None and model is not None and hasattr(model, "forward") and callable(tok):
                self.tok, self.model, self.kind = tok, model, "judge"
                self.status = f"判定モデルの Ruri を使い回す（{type(obj).__name__}）"
                return True
        self.status = "判定モデルの Ruri が見つからない"
        return False

    # ---- 自分で読む
    def load(self):
        if self.kind:
            return
        if self.mode == "lexical":
            self.kind, self.status = "lexical", "文字の重なり（MEMORY_RURI=lexical）"
            return
        errs = []
        try:
            from sentence_transformers import SentenceTransformer
            self.st = SentenceTransformer(self.model_name)
            self.kind, self.status = "own-st", f"{self.model_name}（sentence-transformers）"
            return
        except Exception as e:
            errs.append(f"st: {type(e).__name__}: {e}")
        try:
            import torch  # noqa: F401
            from transformers import AutoModel, AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModel.from_pretrained(self.model_name).eval()
            self.kind, self.status = "own-hf", f"{self.model_name}（transformers・平均）"
            return
        except Exception as e:
            errs.append(f"hf: {type(e).__name__}: {e}")
        self.kind, self.status = "lexical", "文字の重なり（Ruri が読めない: " + " / ".join(errs)[:300] + "）"

    @property
    def min_sim(self) -> float:
        return MEMORY_MIN_LEX if self.kind == "lexical" else MEMORY_MIN_SIM

    def _encode(self, texts: List[str]):
        import numpy as np
        if self.kind == "own-st":
            v = self.st.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
            return np.asarray(v, dtype="float32")
        import torch
        dev = next(self.model.parameters()).device
        enc = self.tok(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
        enc = {k: v.to(dev) for k, v in enc.items() if k in ("input_ids", "attention_mask", "token_type_ids")}
        with torch.no_grad():
            out = self.model(**enc)
            h = out.last_hidden_state if hasattr(out, "last_hidden_state") else out[0]
            m = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
            v = (h * m).sum(1) / m.sum(1).clamp(min=1)
            v = torch.nn.functional.normalize(v.float(), dim=-1)
        return v.cpu().numpy()

    def scores(self, query: str, docs: List[Tuple[str, str]]) -> List[float]:
        """docs = [(キー, 文)]。返り値は docs と同じ順の近さ。"""
        self.load()
        if not docs:
            return []
        if self.kind == "lexical":
            return [lexical_sim(query, d) for _, d in docs]
        with self.lock:
            return self._scores(query, docs)

    def _scores(self, query: str, docs: List[Tuple[str, str]]) -> List[float]:
        try:
            import numpy as np
            need = [(k, d) for k, d in docs if (k, d) not in self.cache]
            if need:
                vecs = self._encode([D_PREFIX + d for _, d in need])
                for (k, d), v in zip(need, vecs):
                    self.cache[(k, d)] = v
                if len(self.cache) > 5000:            # 増えすぎたら捨てる
                    self.cache = {kd: self.cache[kd] for kd in list(self.cache)[-2000:]}
            q = self._encode([Q_PREFIX + query])[0]
            return [float(np.dot(q, self.cache[(k, d)])) for k, d in docs]
        except Exception as e:                         # 途中で失敗したら文字の重なりで続ける
            self.kind, self.status = "lexical", f"文字の重なり（Ruri で失敗: {type(e).__name__}: {e}）"
            return [lexical_sim(query, d) for _, d in docs]


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
    sims = embedder.scores(text, [(m["id"], m["text"]) for m in cands])
    info["method"] = embedder.kind
    order = sorted(zip(cands, sims), key=lambda x: -x[1])
    info["scores"] = [(m["id"], round(s, 3)) for m, s in order[:3]]
    th = embedder.min_sim
    t = unicodedata.normalize("NFKC", text)
    names = [n for n in name_map.values() if len(n) >= 2 and n in t]
    picked = []
    for m, s in order:
        hit_name = any(n in m["text"] for n in names)
        if s >= th or hit_name or (strict and not picked):   # 日付できっちりしぼれたら1位は近さが低くても使う
            picked.append(m)
        if len(picked) >= MEMORY_TOPK:
            break
    if names and picked:                       # 名前を聞かれたら、その名前が入っている思い出を先に
        picked.sort(key=lambda m: not any(n in m["text"] for n in names))
    if not picked:
        info["why"] = f"近さが足りない（1位 {order[0][1]:.3f} < {th}）"
    info["picked"] = [m["id"] for m in picked]
    return picked, info


# ---------------------------------------------------------------- 前の代（journeys）
GREW = {"active": "元気になった", "affection": "人懐っこくなった", "talkative": "おしゃべりになった",
        "logic": "物知りになった", "curious": "好奇心いっぱいになった", "night": "夜ふかしするようになった"}
SPEECH_SKIP = {"", "標準", "standard", "none", "None"}


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


# ---------------------------------------------------------------- チェック
GENERIC = {"飼い主", "一緒", "思い出", "今日", "昨日", "この前", "前に", "お話", "言葉", "そのころ", "おととい",
           "あのお", "お友だち", "お店", "場所", "学校", "会社", "イベント", "食べもの"}
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
    if kind != "current":
        for n in current_names:
            if len(n) >= 2 and n in t:
                reasons.append(f"前の代の話に今の飼い主の名前（{n}）")
    return (not reasons), reasons


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


def _ends_past(t: str) -> bool:
    return bool(re.search(r"(?:た|だ)$", t))


def template_reply(kind: str, lines: List[str], p: PetProfile, label: str = "") -> str:
    """思い出の1行目だけで作る決まった返事。"""
    t = lines[0].rstrip("。")
    if kind == "current":
        s = f"{label}{t}よね" if _ends_past(t) else f"「{t}」のこと"
        if p.stage == 1:
            return _baby(f"うん！{s}。", p)          # 読点で切られないよう「、」を入れない
        return f"うん、覚えてるよ！{s}。" if _ends_past(t) else f"うん、{s}覚えてるよ！"
    who = "最初の飼い主さん" if kind == "first" else "前の飼い主さん"
    s = f"{who}とは{t}んだ" if _ends_past(t) else f"{who}とのことは「{t}」って覚えてるよ"
    if p.stage == 1:
        return _baby(f"{s}。", p)
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


def build_hint(kind: str, lines: List[str]) -> str:
    """モデルにだけ見せるヒント（答えの中身まで書く。ペット自身の hint_ans と同じ考え）。"""
    if kind == "current":
        return f"（「{lines[0]}」ことを覚えていると答える）"
    who = "最初の飼い主さん" if kind == "first" else "前の飼い主さん"
    return f"（{who}とは「{lines[0]}」と答える）"


# ---------------------------------------------------------------- 本体
class MemoryTalk:
    def __init__(self, chat, embedder: Optional[Embedder] = None, temperature: float = MEMORY_TEMP):
        self.chat, self.temperature = chat, temperature
        self.embedder = embedder or Embedder()

    def materials(self, kind: str, p: PetProfile, user_text: str, memories, name_map, journeys,
                  today: date) -> Tuple[List[str], dict, str]:
        """【覚えていること】の文・記録・日付の言葉。文が空なら「覚えてない」。"""
        info: Dict[str, Any] = {"kind": kind}
        if kind == "current":
            items = parse_memories(memories, name_map)
            picked, sel = select_memories(self.embedder, user_text, items, name_map, today)
            info.update(sel)
            labels = [day_label(m["date"], today) for m in picked]
            lines = [(f"{lb}、" if lb else "") + m["text"] for m, lb in zip(picked, labels)]
            # 決まった返事用に、1件目の日付の言葉を別に持つ
            info["label"] = labels[0] if picked else ""
            info["_plain"] = [m["text"] for m in picked]
            return lines, info, info["label"]
        j = pick_journey(journeys, kind, p)
        info["n"] = len(journeys or [])
        if j is None:
            info["why"] = "旅の記録がない"
            return [], info, ""
        info["generation"] = j.get("generation")
        lines = journey_lines(j)
        info["_plain"] = lines
        if not lines:
            info["why"] = "旅の記録が空"
        return lines, info, ""

    def reply(self, p: PetProfile, hist: List[dict], user_text: str, memories=None, name_map=None,
              journeys=None, today: Optional[date] = None):
        """返り値: (返事, generator, persona)。"""
        today = today or datetime.now(TZ).date()
        name_map = norm_name_map(name_map)
        kind = memory_kind(user_text)
        lines, info, label = self.materials(kind, p, user_text, memories, name_map, journeys, today)
        plain = info.pop("_plain", [])
        info.update({"lines": lines, "check": None, "reasons": []})
        persona_base = {"stage": p.stage}

        if not lines:
            only = kind != "current" and not journeys and p.owners == 1
            info["check"] = "dont_know"
            return dont_know_reply(kind, p, only_owner=only), "memory-dontknow", {**persona_base, "memory": info}

        if not self.chat.ready:
            info["check"] = "template（性格LoRA が使えない）"
            return template_reply(kind, plain, p, label), "memory-template", {**persona_base, "memory": info}

        reply, persona = self.chat.reply(p, hist, user_text, extra=build_extra(kind, lines, p),
                                         sampling={"temperature": self.temperature}, extra_first=True,
                                         model_text=user_text + build_hint(kind, plain))
        raw = persona.get("raw") or reply
        ok, reasons = memory_check(raw, plain, kind, list(name_map.values()))
        if ok and reply and p.stage != 1 and LEFTOVER_RE.search(reply):
            ok, reasons = False, ["伏せ字が残っている"]
        if ok and reply:
            info["check"] = "ok"
            persona["memory"] = info
            return reply, "lfm2.5-lora-t04b-memory", persona
        info.update({"check": "replaced", "reasons": reasons or ["空の返事"], "original": reply})
        persona["memory"] = info
        return template_reply(kind, plain, p, label), "memory-template", persona