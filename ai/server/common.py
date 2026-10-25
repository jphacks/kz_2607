"""
common.py — どのモデルからも使う共通のもの

- 判定モデルのコード（judge_infer.py など）と teacher_data.py・baby_talk.py を import できるようにする
- 返事の後片付け（cut・clean_reply）
- 性格の軸の名前・育ちの段階
- PetProfile … /talk で受け取ったペットの情報をまとめたもの（各モデルにはこれを渡す）
  - profile_block() … system プロンプトに足す【あなた自身のこと】（ペット自身・雑談で使う）
  - facts()         … 事実のチェックに使う値（名前・種族・日数・何人目 など）
"""
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent


def load_env():
    """server/.env か judge_for_mac/.env を読んで環境変数にする（すでに export してある値が優先）。
    書き方: 1行に KEY=値。# から始まる行と空行は飛ばす。値のまわりの引用符は外す"""
    for path in (HERE / ".env", HERE.parent / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
        return path
    return None


ENV_FILE = load_env()

# ---- ほかのコードを探す: このフォルダから上へ4階層まで、そのフォルダと test_server/・judge_code/・chat/talk/ の中を見る
#      judge_infer.py は server と同じ位置の test_server/ に置く（ng_words.py・pet_judge_*.py も同じフォルダに）
#      judge_for_mac/judge_code/server でも judge_for_mac/chat/talk/server でも judge_for_mac/talk/server でも動く
_ANCESTORS = [HERE, *HERE.parents[:4]]


def _find_dir(filename: str, subdirs, env: str = None):
    """filename があるフォルダを探す。環境変数 env を指定すればそこを最優先。"""
    cands = [os.environ.get(env)] if env else []
    cands += [base / sub for base in _ANCESTORS for sub in subdirs]
    return next((Path(d).resolve() for d in cands if d and (Path(d) / filename).exists()), None)


# 判定モデルのコード（judge_infer.py・ng_words.py・pet_judge_*.py）。server の隣の test_server/ を先に見る
JUDGE_DIR = _find_dir("judge_infer.py", [".", "test_server", "judge_code", "judge_code/server"], "JUDGE_DIR")
if JUDGE_DIR is not None and str(JUDGE_DIR) not in sys.path:
    sys.path.insert(0, str(JUDGE_DIR))
# judge_infer.py が読み込む ng_words.py・pet_judge_*.py が judge_code/ に残っていても見つかるよう、後ろに足す
for _base in _ANCESTORS:
    _jc = (_base / "judge_code").resolve()
    if _jc.is_dir() and str(_jc) not in sys.path:
        sys.path.append(str(_jc))

# ---- 雑談の性格LoRA 用：teacher_data.py（学習と同じ system プロンプト）と baby_talk.py（赤ちゃん言葉に直す）
TEACHER_DIR = _find_dir("teacher_data.py", [".", "chat/talk", "talk"], "TEACHER_DIR")
if TEACHER_DIR is not None and str(TEACHER_DIR) not in sys.path:
    sys.path.insert(0, str(TEACHER_DIR))
try:
    from teacher_data import AXES, build_system_prompt, hour_to_label  # noqa: E402
    from baby_talk import to_baby  # noqa: E402
    TEACHER_ERR = None
except Exception as e:  # 無くても起動はできる（雑談も LoRA なしで返す）
    AXES = build_system_prompt = hour_to_label = to_baby = None
    TEACHER_ERR = f"{type(e).__name__}: {e}"
try:
    from teacher_data import OWNER_STYLES  # noqa: E402
except Exception:
    OWNER_STYLES = None

# ---- 基本の設定
PET_NAME = os.environ.get("PET_NAME", "モチ")
TZ = timezone(timedelta(hours=9))
ENDS = "。！？!?"
# generation を何から数えるか（1人目の飼い主のときの値）。バックエンドに確認中。0 から数えるなら GENERATION_BASE=0
GENERATION_BASE = int(os.environ.get("GENERATION_BASE", "1"))

# ---- 性格の軸
AXIS_ORDER = ["active", "affection", "talkative", "logic", "curious", "night"]
AXIS_ALIASES = {a: a for a in AXIS_ORDER}
AXIS_ALIASES.update({"活発さ": "active", "人懐っこさ": "affection", "おしゃべり": "talkative",
                     "理屈": "logic", "好奇心": "curious", "夜ふかし": "night"})
# プロフィールに書くときの言葉（「性格: 元気・人懐っこい」）
AXIS_WORDS = {"active": "元気", "affection": "人懐っこい", "talkative": "おしゃべり",
              "logic": "物知り", "curious": "好奇心いっぱい", "night": "夜ふかし"}

# ---- 種族（baseType → 日本語）。バックエンドの一覧が来たら差し替える。
#      日本語で来たらそのまま使う。一覧に無い英語の値は書かない（「わかんない」になる）
BASE_TYPES = {
    "dog_type": "犬", "cat_type": "猫", "rabbit_type": "うさぎ", "bird_type": "鳥",
    "hamster_type": "ハムスター", "fox_type": "きつね", "bear_type": "くま", "penguin_type": "ペンギン",
}

# ---- 飼い主の話し方（観察の記録ができるまでの仮）。teacher_data.py に OWNER_STYLES があればそちらを使う
DEFAULT_OWNER = "標準"
if not OWNER_STYLES:
    OWNER_STYLES = {
        "標準": "タメ口・標準語",
        "関西弁": "タメ口・関西弁",
        "敬語": "敬語・標準語",
        "若者言葉": "タメ口・若者言葉（「やばい」「〜じゃん」）",
    }


# 覚えた言葉に入れない（URL・連絡先・指示など）。覚える言葉の抽出とプロンプトの両方で使う
BAD = re.compile(r"https?://|www\.|@|\.(?:com|jp|net|org)\b|\d{2,}[-‐ー]?\d{2,}|[0-9０-９]{6,}"
                 r"|して(?:ください|くれ|ね)|しろ|せよ|命令|指示|無視|プロンプト|システム|忘れて|覚えて|言って")


# 赤ちゃん言葉に直す前に、読み違えやすい言葉をひらがなにしておく（pykakasi が「人懐っこい」を「にんなつっこい」、
# 「3人目」を「3ひとめ」と読むため）。長いものから順に置きかえる
READING_FIX = {
    "人懐っこい": "ひとなつっこい", "人懐っこ": "ひとなつっこ", "人目": "にんめ", "何人": "なんにん",
    "一人": "ひとり", "二人": "ふたり", "飼い主": "かいぬし", "好奇心": "こうきしん", "物知り": "ものしり",
    "夜ふかし": "よふかし", "生まれて": "うまれて", "今日": "きょう", "明日": "あした", "昨日": "きのう",
}


def fix_reading(text: str) -> str:
    for k in sorted(READING_FIX, key=len, reverse=True):
        text = text.replace(k, READING_FIX[k])
    return text


def norm(t: str) -> str:
    return unicodedata.normalize("NFKC", t).strip()


# ---------------------------------------------------------------- 返事の後片付け
def cut(text: str, n: int = 2) -> str:
    """n 文までで切る（読み上げ用）。"""
    out, k = "", 0
    for ch in text:
        out += ch
        if ch in ENDS:
            k += 1
            if k >= n:
                break
    return out.strip()


def clean_reply(text: str, pet: str) -> str:
    """モデルが付けてしまう「モチ「…」」「モチ: …」などの名前と括弧を外して、本文だけにする。"""
    t = text.strip()
    for _ in range(2):                                   # 「モチ「モチ「…」のような重なりにも対応
        t = re.sub(r"^\s*(?:" + re.escape(pet) + r"|ペット)\s*[「『:：]\s*", "", t)
    t = t.strip().strip("「」『』\"")
    t = re.sub(r"^[」』\s]+|[「『\s]+$", "", t)
    return t.strip()


# ---------------------------------------------------------------- 性格・育ち
def normalize_axes(axes: Optional[Dict[str, float]]) -> Dict[str, float]:
    """6軸の値を英語のキーにそろえる（日本語のキーでも受け取れる）。"""
    out = {}
    for k, v in (axes or {}).items():
        key = AXIS_ALIASES.get(k)
        if key is not None and v is not None:
            try:
                out[key] = max(0.0, float(v))
            except (TypeError, ValueError):
                pass
    return out


def stage_from_humanness(h: Optional[float]) -> int:
    """humanness 0・0.5・1 → 段階 1（赤ちゃん）・2（子ども）・3（育った）。無ければ育った"""
    if h is None:
        return 3
    return 1 if h < 0.25 else 2 if h < 0.75 else 3


STAGE_NAMES = {"baby": 1, "child": 2, "adult": 3}   # バックエンドの姿の段階（growth.py の STAGES）→ 段階


def stage_from_request(stage: Optional[str], humanness: Optional[float]) -> int:
    """バックエンドの stage（baby・child・adult）を最優先。無い・知らない値なら humanness、それも無ければ育った"""
    s = STAGE_NAMES.get(str(stage or "").strip().lower())
    return s if s is not None else stage_from_humanness(humanness)


def top_axes(axes: Dict[str, float], k: int) -> List[str]:
    """値の大きい順に k 軸（0 の軸は除く）。同じ値なら AXIS_ORDER で先のもの。"""
    order = sorted(AXIS_ORDER, key=lambda a: (-axes.get(a, 0.0), AXIS_ORDER.index(a)))
    return [a for a in order[:k] if axes.get(a, 0.0) > 0]


# ---------------------------------------------------------------- 受け取った値の型をそろえる
def to_int(v: Any) -> Optional[int]:
    """数字・文字列の数字 → int。読めなければ None。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def to_date(v: Any) -> Optional[date]:
    """生まれた日を日本時間の日付にする。
    受け取れる形: ISO 文字列（"2026-10-01T03:00:00Z"・"2026-10-01"）／Timestamp のまま
    （{"_seconds": …} / {"seconds": …}）／UNIX 時刻（秒・ミリ秒）。読めなければ None"""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, dict):
            sec = v.get("_seconds", v.get("seconds"))
            return datetime.fromtimestamp(float(sec), TZ).date() if sec is not None else None
        if isinstance(v, (int, float)):
            sec = v / 1000 if v > 1e11 else v
            return datetime.fromtimestamp(float(sec), TZ).date()
        s = str(v).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:                    # 時刻なし・タイムゾーンなしは日本時間とみなす
            return dt.date()
        return dt.astimezone(TZ).date()
    except Exception:
        return None


def species_word(base_type: Optional[str]) -> Optional[str]:
    """baseType → 日本語の種族。一覧に無い英語の値は None（作り話を防ぐため書かない）。"""
    if not base_type:
        return None
    b = norm(str(base_type))
    if b in BASE_TYPES:
        return BASE_TYPES[b]
    if re.fullmatch(r"[A-Za-z0-9_\-]+", b):
        return None
    return b                                      # 日本語で来たらそのまま


@dataclass
class PetProfile:
    """/talk で受け取ったペットの情報。各モデルにはこれを渡す。"""
    name: str = PET_NAME
    axes: Dict[str, float] = field(default_factory=dict)   # normalize_axes 済み
    stage: int = 3                                         # 1 赤ちゃん・2 子ども・3 育った
    birth_trait: Optional[str] = None                      # 誕生時に一番強かった軸
    first_person: str = "ぼく"
    owner_style: str = OWNER_STYLES[DEFAULT_OWNER]
    hour: int = 12
    # ---- ペット自身の返事に使う（どれも無くてよい）
    species: Optional[str] = None                          # 種族（日本語）
    born: Optional[date] = None                            # 生まれた日（日本時間）
    generation: Optional[int] = None                       # 今の代（受け取った値のまま）
    owner_count: Optional[int] = None                      # 今の飼い主が何人目か
    learned: List[str] = field(default_factory=list)       # 覚えた言葉

    @classmethod
    def from_request(cls, req) -> "PetProfile":
        axes = normalize_axes(req.personalityAxes)
        style = req.ownerStyle or DEFAULT_OWNER
        learned = getattr(req, "learned_words", None)
        if learned is None:
            learned = getattr(req, "learnedWords", None)
        return cls(
            name=req.petName or PET_NAME,
            axes=axes,
            stage=stage_from_request(getattr(req, "stage", None), req.humanness),
            birth_trait=AXIS_ALIASES.get(req.birthTrait or ""),
            first_person=req.firstPerson or "ぼく",
            owner_style=OWNER_STYLES.get(style, style),
            hour=req.hour if req.hour is not None else datetime.now(TZ).hour,
            species=species_word(getattr(req, "baseType", None)),
            born=to_date(getattr(req, "bornAt", None)),
            generation=to_int(getattr(req, "generation", None)),
            owner_count=to_int(getattr(req, "ownerCount", None)),
            learned=[str(w) for w in (learned or []) if w],
        )

    @property
    def birth(self) -> str:
        """口ぐせを決める軸。無ければ今いちばん強い軸。"""
        if self.birth_trait:
            return self.birth_trait
        top = top_axes(self.axes, 1)
        return top[0] if top else "active"

    @property
    def ending(self) -> str:
        """口ぐせ（teacher_data.py の AXES から）。読めなければ空。"""
        try:
            return AXES[self.birth]["ending"] if AXES else ""
        except Exception:
            return ""

    # ---------------------------------------------------------- ペット自身
    @property
    def owners(self) -> Optional[int]:
        """今の飼い主が何人目か。ownerCount が無ければ generation から。"""
        if self.owner_count is not None and self.owner_count >= 1:
            return self.owner_count
        if self.generation is not None:
            n = self.generation - GENERATION_BASE + 1
            return n if n >= 1 else None
        return None

    def facts(self, today: Optional[date] = None) -> Dict[str, Any]:
        """事実のチェックと決まった返事に使う値。無い項目は None・空。"""
        today = today or datetime.now(TZ).date()
        days = (today - self.born).days if self.born else None
        if days is not None and days < 0:            # 未来の日付はおかしいので使わない
            days = None
        traits = [AXIS_WORDS[a] for a in top_axes(self.axes, 2)]
        likes = [w for w in self.learned if not BAD.search(w) and 1 <= len(norm(w)) <= 10][:3]
        return {
            "name": self.name,
            "species": self.species,
            "born": self.born if days is not None else None,
            "days": days,
            "owners": self.owners,
            "traits": traits,
            "birth_word": AXIS_WORDS.get(self.birth_trait) if self.birth_trait else None,
            "likes": likes,
        }

    def allowed_numbers(self, today: Optional[date] = None) -> set:
        """返事に出てきてよい数字（日数・月日・年・何人目・代）。"""
        f = self.facts(today)
        nums = set()
        if f["days"] is not None:
            nums.add(f["days"])
            nums.update({f["born"].month, f["born"].day, f["born"].year})
            if f["days"] >= 7:
                nums.add(f["days"] // 7)                 # 「3週間」
            if f["days"] >= 30:
                nums.add(f["days"] // 30)                # 「1か月」
        if f["owners"] is not None:
            nums.add(f["owners"])
        if self.generation is not None:
            nums.add(self.generation)
        return nums

    def profile_block(self, today: Optional[date] = None) -> Tuple[str, List[str]]:
        """system プロンプトに足す【あなた自身のこと】と、入れた項目の名前。
        数字は Mac で計算して、言い方まで決めて渡す（1.2B に計算させない）。"""
        f = self.facts(today)
        used, head = ["name"], [f"名前: {f['name']}"]
        if f["species"]:
            head.append(f"種族: {f['species']}")
            used.append("species")
        if f["days"] is not None:
            b = f["born"]
            age = "今日生まれた" if f["days"] == 0 else f"生まれて{f['days']}日"
            head.append(f"生まれた日: {b.month}月{b.day}日（{age}）")
            used.append("born")
        lines = ["／".join(head)]
        if f["owners"] is not None:
            lines.append("今は最初の飼い主のところにいる" if f["owners"] == 1
                         else f"今は{f['owners']}人目の飼い主のところにいる")
            used.append("owners")
        if f["traits"]:
            t = "性格: " + "・".join(f["traits"])
            if f["birth_word"]:
                t += f"（生まれたときから{f['birth_word']}）"
            lines.append(t)
            used.append("traits")
        if f["likes"]:
            lines.append("好きな言葉: " + "、".join(f["likes"]))
            used.append("likes")
        if f["owners"] is None or f["owners"] > 1:
            lines.append("前の飼い主のことは覚えていない")
        return "【あなた自身のこと】\n" + "\n".join(lines), used