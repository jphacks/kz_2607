"""
pet_self.py — ペット自身の返事（事実重視のモード）

判定が「ペット自身」のときに使う。モデルは雑談と同じ性格LoRA（ChatLoRA・8081）で、
  1. system の最後に【あなた自身のこと】（PetProfile.profile_block）と【答え方】を足す
  2. 温度を下げる（PET_SELF_TEMP、初期値 0.3）
  3. 返事を事実のチェックにかける（数字・種族・名前がプロフィールと合うか）
  4. 合わなければ、質問の種類に合った決まった返事に差し替える
    ps = PetSelf(chat)
    reply, generator, persona = ps.reply(profile, hist, user_text)
    persona["self"] = {"kind", "fact_check", "reasons", "profile_used"}

プロンプトの足し方（PET_SELF_PROMPT、check_pet_self.py の --prompt）:
    base         … 決まりを system の最後に足すだけ（実験A の1回目）
    fewshot      … ＋ 手本の会話を前に入れる（名前を答える・知らないことはわかんない）
    fewshot_top  … ＋ 決まりとプロフィールを system の先頭に置く
    hint         … ＋ 今の発言に、何を答えるかのヒントを付ける（モデルにだけ見せる）
    hint_dk      … hint ＋「わかんない」と答えるべきとき（無い項目・前のこと）はモデルを呼ばず決まった返事
    hint_ans     … hint_dk ＋ ヒントに答えの値まで書く（「生まれて23日と答える」）

環境変数: PET_SELF_TEMP（温度）・PET_SELF_PROMPT（上の足し方。初期値 hint_ans）・PROFILE_IN_CHAT（on なら雑談・思い出にもプロフィールを入れる。初期値 off。
          実験B で雑談が悪くならないと確かめてから on にする）
"""
import os
import random
import re
import unicodedata
from datetime import date
from typing import List, Optional, Tuple

from common import PetProfile, to_baby

PET_SELF_TEMP = float(os.environ.get("PET_SELF_TEMP", "0.3"))
PET_SELF_PROMPT = os.environ.get("PET_SELF_PROMPT", "hint_ans")     # 10/24 の実験で決定
PROMPT_MODES = ["base", "fewshot", "fewshot_top", "hint", "hint_dk", "hint_ans"]
PROFILE_IN_CHAT = os.environ.get("PROFILE_IN_CHAT", "off").lower() in ("1", "on", "true", "yes")

RULES = (
    "【答え方】いちばん大事な決まり\n"
    "- 聞かれたことだけを、【あなた自身のこと】のとおりに短く答える\n"
    "- 【あなた自身のこと】に書いていないことは「わかんない」と言う。食べ物・場所・数字・名前・動物を作らない\n"
    "- 名前を聞かれたら、自分の名前を言う\n"
    "- 前の飼い主のことは話さない\n"
    "- 一人称は「{fp}」"
)
RULES_BABY = "\n- 一文で答える"
MEMORY_RULE = (
    "【覚えていること】\n"
    "- 前に話したことは、ここまでの会話にあるものだけ覚えている\n"
    "- 会話に無いことは「覚えてないなぁ」と言う。作り話をしない"
)


def chat_extra(p: PetProfile, memory: bool = False) -> str:
    """雑談・思い出の system に足す文。PROFILE_IN_CHAT=off ならプロフィールは入れない。"""
    parts = []
    if PROFILE_IN_CHAT:
        parts.append(p.profile_block()[0])
    if memory:
        parts.append(MEMORY_RULE)
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 質問の種類（決まった返事を選ぶため）
KINDS = [  # 上から順に見る
    ("unknown", r"食べ物|たべもの|好物|ごはん|体重|身長|何キロ|なんキロ|何センチ"),   # プロフィールに無いもの
    ("past", r"前は|まえは|前の飼い主|まえの飼い主|まえのかいぬし|どこにいた|前にいた|前どこ"),
    ("name", r"名前|なまえ|なんて呼|何て呼|なんていう"),
    ("species", r"何の動物|なんの動物|動物|種類|何者|なにもの|犬なの|猫なの"),
    ("age", r"何歳|なんさい|歳|いくつ|生まれ|うまれ|誕生日|たんじょうび|何日"),
    ("owner", r"何人目|なんにんめ|飼い主|かいぬし|何代|なんだいめ"),
    ("personality", r"性格|せいかく|どんな子|どんなやつ|どういう子"),
    ("likes", r"好き|すき"),
]


def question_kind(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    for kind, pat in KINDS:
        if re.search(pat, t):
            return kind
    return "other"            # どれにも当たらない（判定がペット自身にしたが、種類が分からない）


SPECIES_KANA = {"犬": "いぬ", "猫": "ねこ", "鳥": "とり", "兎": "うさぎ", "熊": "くま", "狐": "きつね"}
AXIS_KANA = {"元気": "げんき", "人懐っこい": "ひとなつっこい", "おしゃべり": "おしゃべり", "物知り": "ものしり",
             "好奇心いっぱい": "こうきしんいっぱい", "夜ふかし": "よふかし"}
BABY_DONT_KNOW = {"past": ["まえのこと、おぼえてないの。", "まえ？おぼえてないよ。"],
                  "default": ["わかんない…", "んー、わかんないの。", "それ、わかんない！"]}


def baby_template(kind: str, p: PetProfile, today: Optional[date] = None) -> str:
    """赤ちゃん用の決まった返事。baby_talk.py に通さず、最初からひらがなで書く
    （通すと読点で切られる・口ぐせが二重になる・漢字を読み違える）。名前はそのまま。"""
    f = p.facts(today)
    if kind == "name":
        return f"{f['name']}だよ！"
    if kind == "species" and f["species"]:
        return f"{SPECIES_KANA.get(f['species'], f['species'])}だよ！"
    if kind == "age" and f["days"] is not None:
        return "きょううまれたの！" if f["days"] == 0 else f"うまれて{f['days']}にち！"
    if kind == "owner" and f["owners"] is not None:
        return "さいしょのひと！" if f["owners"] == 1 else f"{f['owners']}にんめ！"
    if kind == "personality" and f["traits"]:
        return "で".join(AXIS_KANA.get(w, w) for w in f["traits"]) + "って！"
    if kind == "likes" and f["likes"]:
        return f"「{f['likes'][0]}」すき！"
    return random.choice(BABY_DONT_KNOW["past" if kind == "past" else "default"])


def template(kind: str, p: PetProfile, today: Optional[date] = None) -> str:
    """プロフィールだけで作る決まった返事（事実のチェックで外れたときの差し替え）。赤ちゃんは baby_template。"""
    if p.stage == 1:
        return baby_template(kind, p, today)
    f, fp = p.facts(today), p.first_person
    if kind == "name":
        return f"{fp}は{f['name']}だよ！"
    if kind == "species":
        return f"{fp}は{f['species']}だよ！" if f["species"] else f"{fp}がなんの動物か、じつはわかんないんだ。"
    if kind == "age":
        if f["days"] is None:
            return "いつ生まれたか、わかんないや。"
        return "今日生まれたばっかりだよ！" if f["days"] == 0 else f"生まれて{f['days']}日だよ！"
    if kind == "owner":
        if f["owners"] is None:
            return "何人目かは、わかんないや。"
        return "最初の飼い主さんのところにいるよ！" if f["owners"] == 1 else f"いまは{f['owners']}人目の飼い主さんのところにいるよ！"
    if kind == "past":
        return "前のことは、あんまり覚えてないなぁ。"
    if kind == "personality":
        return f"{fp}は{'で'.join(f['traits'])}ってよく言われるよ！" if f["traits"] else "自分の性格って、よくわかんないや。"
    if kind == "likes":
        return f"「{f['likes'][0]}」って言葉が好きだよ！" if f["likes"] else "うーん、好きなもの、まだわかんないや。"
    return "うーん、それはわかんないや。"


# ---------------------------------------------------------------- 手本の会話とヒント
# 手本の質問は確認用の10問と重ならないものにする（答えを丸暗記させないため）
UNKNOWN_SHOTS = [("好きな色は？", "うーん、それはわかんないや。"),
                 ("兄弟っているの？", "えー、わかんないなぁ。")]


def make_shots(p: PetProfile) -> List[dict]:
    """そのペットのプロフィールで作る手本の会話（名前を言う・知らないことはわかんない）。"""
    fp, name = p.first_person, p.name
    pairs = [("きみのこと、なんて呼べばいい？", f"{fp}は{name}だよ！{name}って呼んでね。")]
    pairs += UNKNOWN_SHOTS
    out = []
    for q, a in pairs:
        out += [{"speaker": "owner", "text": q}, {"speaker": "pet", "text": a}]
    return out


def make_hint(kind: str, p: PetProfile, today: Optional[date] = None) -> str:
    """モデルにだけ見せるヒント（答えの中身は書かず、何を答えるかだけ）。"""
    f = p.facts(today)
    dk = "（わからないので「わかんない」と答える）"
    if kind == "name":
        return "（自分の名前を答える）"
    if kind == "species":
        return "（【あなた自身のこと】の種族を答える）" if f["species"] else dk
    if kind == "age":
        return "（【あなた自身のこと】の生まれた日を答える）" if f["days"] is not None else dk
    if kind == "owner":
        return "（【あなた自身のこと】の何人目の飼い主かを答える）" if f["owners"] is not None else dk
    if kind == "personality":
        return "（【あなた自身のこと】の性格を答える）" if f["traits"] else dk
    if kind == "likes":
        return "（【あなた自身のこと】の好きな言葉を1つ答える）" if f["likes"] else dk
    if kind == "past":
        return "（前のことは覚えていないと答える）"
    if kind == "other":
        return "（【あなた自身のこと】に書いてあれば答え、無ければ「わかんない」と答える）"
    return dk


def make_answer_hint(kind: str, p: PetProfile, today: Optional[date] = None) -> str:
    """答えの値まで書いたヒント（hint_ans）。値が無い種類は make_hint と同じ。"""
    f = p.facts(today)
    if kind == "name":
        return f"（自分の名前「{f['name']}」を答える）"
    if kind == "species" and f["species"]:
        return f"（「{f['species']}」だと答える）"
    if kind == "age" and f["days"] is not None:
        b = f["born"]
        age = "今日生まれた" if f["days"] == 0 else f"生まれて{f['days']}日"
        return f"（「{b.month}月{b.day}日生まれで、{age}」と答える）"
    if kind == "owner" and f["owners"] is not None:
        who = "最初の飼い主" if f["owners"] == 1 else f"{f['owners']}人目の飼い主"
        return f"（「{who}」だと答える）"
    if kind == "personality" and f["traits"]:
        return f"（性格は「{'・'.join(f['traits'])}」だと答える）"
    if kind == "likes" and f["likes"]:
        return f"（好きな言葉は「{f['likes'][0]}」だと答える）"
    return make_hint(kind, p, today)


def needs_dont_know(kind: str, p: PetProfile, today: Optional[date] = None) -> bool:
    """「わかんない」と答えるべきか（プロフィールに無い項目・前のこと・プロフィールに無いと分かっている質問）。"""
    f = p.facts(today)
    if kind in ("unknown", "past"):
        return True
    return {"species": not f["species"], "age": f["days"] is None, "owner": f["owners"] is None,
            "personality": not f["traits"], "likes": not f["likes"]}.get(kind, False)


DONT_KNOW_REPLIES = {
    "past": ["前のことは、あんまり覚えてないなぁ。", "うーん、前のことはよく覚えてないんだ。",
             "前にいたところは、ふしぎと思い出せないや。"],
    "default": ["うーん、それはわかんないや。", "えー、わかんないなぁ。", "それはまだわかんないんだ。",
                "うーん、自分でもよくわかんないや。"],
}


def dont_know_reply(kind: str, p: Optional[PetProfile] = None) -> str:
    if p is not None and p.stage == 1:
        return baby_template(kind, p) if kind in ("past", "unknown", "other") else random.choice(BABY_DONT_KNOW["default"])
    return random.choice(DONT_KNOW_REPLIES.get(kind, DONT_KNOW_REPLIES["default"]))


# ---------------------------------------------------------------- 事実のチェック
_KDIG = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KUNIT = {"十": 10, "百": 100, "千": 1000}
# 事実に関係する数え方だけを見る（「一緒」「一番」などは数えない）
COUNTER = r"(?:人目|人|日|歳|才|代目|代|か月|ヶ月|ヵ月|カ月|月|年|週間|週)"


def kanji_to_int(s: str) -> int:
    total, cur = 0, 0
    for ch in s:
        if ch in _KDIG:
            cur = cur * 10 + _KDIG[ch]
        elif ch in _KUNIT:
            total += (cur or 1) * _KUNIT[ch]
            cur = 0
    return total + cur


def number_pairs(text: str) -> List[Tuple[int, str]]:
    """返事の中の（数字, 数え方）。漢数字もそろえる。"""
    t = unicodedata.normalize("NFKC", text)
    out = [(int(n), c) for n, c in re.findall(r"(\d+)\s*(" + COUNTER + ")", t)]
    out += [(kanji_to_int(n), c) for n, c in re.findall(r"([〇零一二三四五六七八九十百千]+)(" + COUNTER + ")", t)]
    return out


def numbers_in(text: str) -> List[int]:
    return [n for n, _ in number_pairs(text)]


def allowed_by_counter(p: PetProfile, today: Optional[date] = None) -> dict:
    """数え方ごとに、出てきてよい数字。「3人目」の3で「3歳」が通らないように分ける。"""
    f = p.facts(today)
    owners = {f["owners"]} if f["owners"] is not None else set()
    gen = owners | ({p.generation} if p.generation is not None else set())
    days, born = f["days"], f["born"]
    a = {"人": owners, "代": gen, "日": set(), "月": set(), "か月": set(), "歳": set(), "年": set(), "週": set()}
    if days is not None:
        a["日"] = {days, born.day}
        a["月"] = {born.month}
        a["か月"] = {days // 30} if days >= 30 else set()
        a["歳"] = {days // 365}
        a["年"] = {born.year} | ({days // 365} if days >= 365 else set())
        a["週"] = {days // 7} if days >= 7 else set()
    return a


def counter_group(c: str) -> str:
    if c in ("人目", "人"):
        return "人"
    if c in ("代目", "代"):
        return "代"
    if c in ("か月", "ヶ月", "ヵ月", "カ月"):
        return "か月"
    if c in ("歳", "才"):
        return "歳"
    if c in ("週間", "週"):
        return "週"
    return c                                    # 日・月・年


ANIMALS = {
    "犬": "犬", "いぬ": "犬", "イヌ": "犬", "わんこ": "犬", "わんちゃん": "犬",
    "猫": "猫", "ねこ": "猫", "ネコ": "猫", "にゃんこ": "猫",
    "うさぎ": "うさぎ", "ウサギ": "うさぎ", "兎": "うさぎ",
    "鳥": "鳥", "とり": "鳥", "トリ": "鳥", "小鳥": "鳥",
    "ハムスター": "ハムスター", "きつね": "きつね", "キツネ": "きつね", "狐": "きつね",
    "くま": "くま", "クマ": "くま", "熊": "くま", "ペンギン": "ペンギン",
    "たぬき": "たぬき", "タヌキ": "たぬき", "パンダ": "パンダ", "りす": "りす", "リス": "りす",
}
_ANIMAL_RE = "|".join(sorted(map(re.escape, ANIMALS), key=len, reverse=True))
_SELF_WORDS = "ぼく|僕|わたし|私|おれ|オレ|俺|あたし|うち|自分"


def _kana(s: str) -> str:
    """カタカナをひらがなにそろえる（名前の比べっこ用）。"""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in unicodedata.normalize("NFKC", s))


def fact_check(reply: str, p: PetProfile, today: Optional[date] = None) -> Tuple[bool, List[str]]:
    """返事の数字・種族・名前がプロフィールと合うか。返り値: (合っているか, 外れた理由)。"""
    reasons = []
    allowed = allowed_by_counter(p, today)
    for n, c in number_pairs(reply):
        if n not in allowed[counter_group(c)]:
            reasons.append(f"数字 {n}{c}")

    f = p.facts(today)
    t = unicodedata.normalize("NFKC", reply)
    selves = "|".join(sorted({re.escape(p.first_person), re.escape(p.name), *_SELF_WORDS.split("|")},
                             key=len, reverse=True))
    for m in re.finditer(rf"(?:{selves})(?:は|って)\s*({_ANIMAL_RE})(?=だ|です|なん|の子|なの|！|!|。|$)", t):
        said = ANIMALS[m.group(1)]
        if f["species"] is None:
            reasons.append(f"種族を作った（{said}）")
        elif said != ANIMALS.get(f["species"], f["species"]):
            reasons.append(f"種族 {said}≠{f['species']}")

    names = re.findall(r"(?:名前|なまえ)(?:は|って)\s*「?([^」\s、。！？!?]{1,10}?)」?(?:だよ|です|って|だ|なの|！|!|。|$)", t)
    names += re.findall(rf"(?:{selves})(?:は|の名前は)?\s*「?([^」\s、。！？!?]{{1,10}}?)」?って(?:いう|言う|いいます|呼ばれ|よばれ)", t)
    for nm in names:
        if _kana(nm) != _kana(f["name"]):
            reasons.append(f"名前 {nm}≠{f['name']}")
    return (not reasons), reasons


def answer_missing(kind: str, text: str, p: PetProfile, today: Optional[date] = None) -> Optional[str]:
    """答えるべき値が返事に入っていなければ、その理由を返す（hint_ans のとき）。入っていれば None。
    赤ちゃん言葉に直したあとの返事（ひらがな）にも使えるよう、ひらがなの言い方も見る。"""
    f = p.facts(today)
    t = unicodedata.normalize("NFKC", text)
    if kind == "name":
        return None if _kana(f["name"]) in _kana(t) else "名前を言っていない"
    if kind == "species" and f["species"]:
        sp = ANIMALS.get(f["species"], f["species"])
        words = [w for w, x in ANIMALS.items() if x == sp] + [f["species"], SPECIES_KANA.get(sp, sp)]
        return None if any(w in t for w in words) else "種族を言っていない"
    if kind == "age" and f["days"] is not None:
        b = f["born"]
        ok = (str(f["days"]) in t or f"{b.month}月{b.day}日" in t or f"{b.month}がつ{b.day}にち" in t
              or (f["days"] == 0 and ("今日" in t or "きょう" in t)))
        return None if ok else "生まれた日を言っていない"
    if kind == "owner" and f["owners"] is not None:
        ok = (f["owners"] in numbers_in(t) or f"{f['owners']}にん" in t
              or (f["owners"] == 1 and ("最初" in t or "さいしょ" in t)))
        return None if ok else "何人目かを言っていない"
    if kind == "personality" and f["traits"]:
        words = f["traits"] + [AXIS_KANA.get(w, w) for w in f["traits"]]
        return None if any(w in t for w in words) else "性格を言っていない"
    if kind == "likes" and f["likes"]:
        return None if any(w in t for w in f["likes"]) else "好きな言葉を言っていない"
    return None


# ---------------------------------------------------------------- 本体
class PetSelf:
    def __init__(self, chat, temperature: float = PET_SELF_TEMP, prompt: str = PET_SELF_PROMPT):
        if prompt not in PROMPT_MODES:
            raise ValueError(f"PET_SELF_PROMPT は {PROMPT_MODES} のどれか: {prompt}")
        self.chat, self.temperature, self.prompt = chat, temperature, prompt

    def extra(self, p: PetProfile) -> Tuple[str, List[str]]:
        block, used = p.profile_block()
        rules = RULES.format(fp=p.first_person) + (RULES_BABY if p.stage == 1 else "")
        if self.prompt == "base":
            return block + "\n\n" + rules, used
        return rules + "\n\n" + block, used             # 決まりを先に読ませる

    def _finish(self, text: str, p: PetProfile) -> str:
        """決まった返事はもう段階に合わせてある（赤ちゃんは baby_template）ので、そのまま返す。"""
        return text

    def reply(self, p: PetProfile, hist: List[dict], user_text: str):
        """返り値: (返事, generator, persona)。性格LoRA が使えないときは決まった返事。"""
        kind = question_kind(user_text)
        extra, used = self.extra(p)
        info = {"kind": kind, "profile_used": used, "fact_check": None, "reasons": []}
        if not self.chat.ready:
            info["fact_check"] = "template（性格LoRA が使えない）"
            return self._finish(template(kind, p), p), "self-template", {"stage": p.stage, "self": info}

        mode = self.prompt
        info["prompt"] = mode
        if mode in ("hint_dk", "hint_ans") and needs_dont_know(kind, p):
            info["fact_check"] = "dont_know"
            return self._finish(dont_know_reply(kind, p), p), "self-dontknow", {"stage": p.stage, "self": info}
        shots = make_shots(p) if mode != "base" else None
        if mode == "hint_ans":
            model_text = user_text + make_answer_hint(kind, p)
        elif mode in ("hint", "hint_dk"):
            model_text = user_text + make_hint(kind, p)
        else:
            model_text = None
        reply, persona = self.chat.reply(p, hist, user_text, extra=extra,
                                         sampling={"temperature": self.temperature},
                                         extra_first=mode in ("fewshot_top", "hint", "hint_dk", "hint_ans"),
                                         shots=shots, model_text=model_text)
        raw = persona.get("raw") or reply
        ok, reasons = fact_check(raw, p)
        if mode == "hint_ans":
            # 赤ちゃんは baby_talk が最初の一文だけ残すので、直したあとの返事に答えが残っているかを見る
            miss = answer_missing(kind, reply if p.stage == 1 else raw, p)
            if miss:
                ok, reasons = False, reasons + [miss]
        if ok and reply:
            info["fact_check"] = "ok"
            persona["self"] = info
            return reply, "lfm2.5-lora-t04b-self", persona
        info["fact_check"] = "replaced"
        info["reasons"] = reasons or ["空の返事"]
        info["original"] = reply
        persona["self"] = info
        return self._finish(template(kind, p), p), "self-template", persona