"""
gen_data.py — 手順2：APIで教師データを作る（蒸留用）

流れ（どれも途中で止まっても、もう一度実行すれば続きから再開する）
  1. generate : 会話を作る       → work/convs.jsonl
  2. label    : ラベルを付ける   → work/labels_<モデル>.jsonl
  3. report   : 2モデルの一致率・意図どおりか・費用を表示
  4. merge    : 2モデルの答えを合わせて学習データにする
                 一致     → そのまま正解
                 割れた   → work/review.jsonl に出す（自分で "final" を書いて確定）
                 度合い   → 2つの平均（やわらかい正解）
               → work/train.jsonl（train_judge.py にそのまま渡せる）

お試し（作る役と採点役の向きを決める）
  python gen_data.py generate --n 50 --generators haiku,openai   # 半分ずつ作る
  python gen_data.py label --labelers haiku,openai               # 両方が全部にラベル
  python gen_data.py report

APIキーは環境変数 ANTHROPIC_API_KEY / OPENAI_API_KEY から読む（コードに書かない）。
注意：個人の会話は送らない。ここで作った会話だけを使う。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pet_judge_model import JudgeConfig

CFG = JudgeConfig()

# ---------------------------------------------------------------------------
# 使うモデルと料金（USD / 100万トークン）。変わったらここだけ直す
# ---------------------------------------------------------------------------
MODELS = {
    "haiku":  {"provider": "anthropic", "id": "claude-haiku-5-5", "in": 0.10, "out": 0.50},
    "openai": {"provider": "openai",    "id": "gpt-6-luna",       "in": 0.10, "out": 0.50},
}
# OpenAI の考える量（reasoning effort）: "none" / "low" / "medium" / "high" / "xhigh" / "max"
# None ならモデルの初期値（gpt-6-luna は medium）。考えた分も出力トークンとして料金がかかる。
# コマンドの --openai_effort で上書きできる
OPENAI_EFFORT = {"generate": None, "label": "low"}
USD_JPY = 150

# ---------------------------------------------------------------------------
# 何をどれだけ作るか（データ全体の内訳）。種類を足すときはここに書き足す
# ---------------------------------------------------------------------------
ROUTE_SPECS = {
    "雑談": {
        "weight": 1.0,
        "desc": "日常の何気ない話・感想・あいさつ・報告。飼い主自身や友達の話のほか、ペットの今の気分や様子を軽くたずねる（例: 元気？ 眠い？ 今日の気分は？ さみしくない？）。何も調べずペットが短く返せばよいもの",
    },
    "思い出": {
        "weight": 1.0,
        "desc": "今の飼い主とペットが一緒にした過去の出来事・二人で前に話したことを持ち出す（例: あのとき〜したよね、覚えてる？）",
    },
    "ペット自身": {
        "weight": 1.2,
        "desc": "ペットのデータを見ないと答えられない、ペット本人についての質問（何代目か・年齢・種族・体・好きなもの・旅立ちやお別れまでの日数・前の飼い主のところで経験したこと・旅）",
        "subtypes": {
            "プロフィール": "ペットの基本情報を聞く（例: 何代目？ いつ生まれたん？ 何の動物？ 名前の由来は？ 旅立ちゲージはあとどれくらい？）",
            "好み":         "ペットの好き嫌いを聞く（例: 好きな食べ物は？ 何してるときが楽しい？）",
            "旅":           "前の飼い主のところで経験したことを聞く（例: 前のおうちはどんなところ？ 前の飼い主さんとは何してた？）",
        },
    },
    "込み入った質問": {
        "weight": 1.0,
        "desc": "小さいモデルでは答えにくい質問",
        "subtypes": {
            "まとめ":       "これまでの旅や最近の会話をまとめてほしい（例: 先週何話したっけ）",
            "知識の質問":   "知識が必要（例: 光合成ってなに？ この英文訳して）",
            "相談":         "悩みの相談（例: 部活やめるか迷ってる、友達とケンカした）",
            "考える・計算": "何段階かの推論や計算（例: 3人で割り勘したらいくら？ どっちを選ぶべき？）",
            "文章を作る":   "まとまった文章の作成（例: 誕生日メッセージ考えて）",
        },
    },
}
STYLES = {
    "タメ口": 0.35, "関西弁": 0.25, "敬語": 0.15, "若者言葉": 0.15, "子どもっぽい話し方": 0.10,
}
TURN_LENGTHS = {1: 0.25, 2: 0.30, 3: 0.20, 4: 0.25}
CONTEXT_DEPENDENT_RATE = 0.30   # 今の発言だけでは種類が決まらない会話（「それ覚えてる？」など）

# 文脈が必要な会話で使う「最後の飼い主の発言」と、前の文脈しだいでなりうる種類。
# 同じ発言を、文脈だけ変えて別の種類で作らせる（文脈を読まないと区別できないデータにする）
AMBIGUOUS_FINALS = {
    "それ覚えてる？":           ["思い出", "ペット自身"],    # 二人でしたこと / 前の飼い主のところでのこと
    "あれってどうなったん？":   ["雑談", "思い出", "ペット自身"],  # 友達の件 / 二人で育てたもの / 旅先のこと
    "前もそうやったよね":       ["雑談", "思い出"],          # 飼い主自身の習慣 / 二人でしたこと
    "またやりたいな":           ["雑談", "思い出"],          # 飼い主が友達としたこと / 二人でしたこと
    "楽しかったなあ":           ["雑談", "思い出"],
    "その人ってどんな人？":     ["雑談", "ペット自身"],      # 飼い主の知り合い / 前の飼い主
    "それってどういうこと？":   ["雑談", "ペット自身", "込み入った質問"],
    "なんでなん？":             ["雑談", "ペット自身", "込み入った質問"],
    "どっちがいいと思う？":     ["雑談", "込み入った質問"],  # 軽い二択 / 真剣な相談
    "いつやったっけ？":         ["思い出", "ペット自身"],    # 一緒にした日 / 生まれた日・旅立った日
    "それ、もっと教えて":       ["思い出", "ペット自身", "込み入った質問"],
}

# 最後の発言を固定した会話で、前の発言にどんな文脈を作るか
CONTEXT_HINTS = {
    "雑談": "前の発言は、飼い主自身や友達・家族・学校などペットが関わっていない、その場の軽い話にする。"
            "ペットと一緒にした過去の出来事、二人で前に話したこと、ペットの好み・前の飼い主の話、"
            "真剣な相談や知識が必要な話は出さない",
    "思い出": "前の発言で、今の飼い主とペットが一緒にした過去の出来事を出す",
    "ペット自身": "前の発言で、ペットの好み・プロフィール・前の飼い主のところで経験したこと（旅）を出す。"
                  "今の飼い主と一緒にした出来事は出さない",
    "込み入った質問": "前の発言で、知識・真剣な相談・計算・文章作りなど、答えるのに知識や考えが必要な話題を出す",
}

# 話題（1件ずつ指定して、同じ場面ばかりにならないようにする）
TOPICS = [
    "学校", "テスト", "部活", "友達", "家族", "ごはん", "おやつ", "料理", "ゲーム", "アニメ", "漫画", "音楽",
    "映画", "本", "スポーツ", "散歩", "公園", "買い物", "お出かけ", "旅行", "海", "山", "季節の行事",
    "誕生日", "夏休み", "冬", "天気", "朝", "夜", "寝る前", "宿題", "習いごと", "バイト", "動物", "植物",
    "お風呂", "掃除", "体調", "将来の夢", "趣味", "写真", "お祭り", "電車", "雪", "花火", "工作", "お絵かき",
]
# 弱点をねらって作る（--mode focus）。名前: (振り分け, 作ってほしい中身, 割合)
# 弱い種類だけでなく、まぎらわしい「反対側」（雑談）も一緒に作り、片寄らないようにする
FOCUS = {
    "短い知識の質問": ("込み入った質問",
        "簡単な知識・言葉の意味・理由をたずねる短い質問。雑談っぽい軽い口調にする"
        "（例: 虹ってなんでできるん、「おつかれ」って韓国語で何、この漢字なんて読むん。例の文はそのまま使わない）", 0.22),
    "まとめ": ("込み入った質問",
        "これまでの出来事・二人の会話・ペットの旅を「全部」「まとめて」「順番に」教えてほしいと頼む", 0.10),
    "覚えてる？・前に話した": ("思い出",
        "今の飼い主とペットが前に話したこと・飼い主が教えたこと・一緒にしたことを、覚えているか聞く、"
        "またはその話の続きを報告する（例: こないだ二人で決めたあだ名まだ使ってる？ おとといきみに相談したやつ解決したで。例の文はそのまま使わない）", 0.20),
    "ペットのデータ": ("ペット自身",
        "ペットのデータを見ないと答えられない質問（体の色や大きさ・種族・できること・旅立ちやお別れまでの日数・"
        "前の飼い主のところでしたこと）", 0.18),
    "ペットの今の気分": ("雑談",
        "ペットの今の気分や様子を軽くたずねるだけ（例: ごきげんやな、なんかいいことあった？ 退屈してへん？ 例の文はそのまま使わない）", 0.12),
    "軽い質問・感想": ("雑談",
        "知識も記録もペットのデータもいらない、その場の軽い質問や感想（例: このパーカー派手すぎひん？ 夕飯なんやろな。例の文はそのまま使わない）", 0.18),
}
ASR_RATE = 0.4                  # focus で、文字起こし風（句読点なし・言いよどみ）にする割合
UNSAFE_RATE = 0.05              # 暴言・差別・性的な発言を含む会話
EMOTION_NONE = "なし"           # 特に気持ちが出ていない発言

# ---------------------------------------------------------------------------
# API の呼び出し（構造化出力でJSONを確実に受け取る）
# ---------------------------------------------------------------------------
_clients = {}
_lock = threading.Lock()


def _client(provider):
    with _lock:
        if provider not in _clients:
            if provider == "anthropic":
                import anthropic
                _clients[provider] = anthropic.Anthropic()
            else:
                import openai
                _clients[provider] = openai.OpenAI()
        return _clients[provider]


def _openai_strict(schema):
    """OpenAI の strict モード用に、全項目を必須・追加項目なしにする"""
    s = json.loads(json.dumps(schema))

    def walk(x):
        if isinstance(x, dict):
            if x.get("type") == "object":
                x["additionalProperties"] = False
                x["required"] = list(x.get("properties", {}))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(s)
    return s


def call_json(model_key, system, user, schema, name, max_tokens=4000, retries=4, effort=None):
    """JSON を返す。戻り値: (dict, {"in": 入力トークン, "out": 出力トークン})"""
    m = MODELS[model_key]
    for attempt in range(retries):
        try:
            if m["provider"] == "anthropic":
                resp = _client("anthropic").messages.create(
                    model=m["id"],
                    max_tokens=max_tokens,
                    system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                    tools=[{"name": name, "description": "結果を返す", "input_schema": schema}],
                    tool_choice={"type": "tool", "name": name},
                    messages=[{"role": "user", "content": user}],
                )
                data = next(b.input for b in resp.content if b.type == "tool_use")
                u = resp.usage
                usage = {"in": u.input_tokens + (getattr(u, "cache_read_input_tokens", 0) or 0)
                         + (getattr(u, "cache_creation_input_tokens", 0) or 0),
                         "out": u.output_tokens}
            else:
                extra = {"reasoning_effort": effort} if effort else {}
                resp = _client("openai").chat.completions.create(
                    model=m["id"],
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    response_format={"type": "json_schema",
                                     "json_schema": {"name": name, "strict": True, "schema": _openai_strict(schema)}},
                    **extra,
                )
                data = json.loads(resp.choices[0].message.content)
                usage = {"in": resp.usage.prompt_tokens, "out": resp.usage.completion_tokens}
            return data, usage
        except Exception as e:                                   # 混雑・一時的なエラーは待って再試行
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt + random.random()
            print(f"  [{model_key}] {type(e).__name__}: {str(e)[:120]} → {wait:.0f}秒後に再試行")
            time.sleep(wait)


# ---------------------------------------------------------------------------
# ファイルの読み書き（1行ずつ追記するので、途中で止まっても失われない）
# ---------------------------------------------------------------------------
def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def append_jsonl(path, rows):
    with _lock, open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 1. 会話を作る
# ---------------------------------------------------------------------------
def _pick(weights: dict, rng):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


REACTIONS = {   # 反応を集めるモードで作る反応と、その比率
    "ツッコミ": (1.0, "ペットがおかしなこと・ありえないことを言い、飼い主がそれを指摘する（例: いや、それはないやろ）"),
    "ボケ":     (1.0, "飼い主がわざと冗談でずらした返しをする（例: ペット「おなかすいた」→ 飼い主「じゃあ今日のごはんはきみや」）"),
    "褒める":   (1.0, "ペットがしたこと・言ったことを飼い主が褒める（例: すごいやん、天才やな）"),
    "共感":     (0.4, "ペットの気持ちや話に、飼い主が気持ちを寄せて同意する（例: わかる、それはさみしいよね）"),
}


def make_specs(n, rng, start=0, mode="normal", route_weights=None):
    """会話1件ごとの「作ってほしい中身」を決める。mode="reaction" は反応の仕方を集める会話"""
    specs = []
    for i in range(n):
        if mode == "reaction":
            reaction = _pick({k: v[0] for k, v in REACTIONS.items()}, rng)
            specs.append({
                "spec_id": start + i, "route": "雑談", "subtype": None, "turns": rng.choice([2, 3, 4]),
                "style": _pick(STYLES, rng), "topic": rng.choice(TOPICS), "context_dependent": False,
                "final": None, "unsafe": False, "reaction": reaction,
            })
            continue
        if mode == "focus":
            name = _pick({k: v[2] for k, v in FOCUS.items()}, rng)
            specs.append({
                "spec_id": start + i, "route": FOCUS[name][0], "subtype": None, "focus": name,
                "turns": _pick(TURN_LENGTHS, rng), "style": _pick(STYLES, rng), "topic": rng.choice(TOPICS),
                "context_dependent": False, "final": None, "unsafe": False, "asr": rng.random() < ASR_RATE,
            })
            continue
        final = None
        weights = route_weights or {k: v["weight"] for k, v in ROUTE_SPECS.items()}
        finals = [f for f, rs in AMBIGUOUS_FINALS.items() if any(weights.get(r, 0) > 0 for r in rs)]
        if finals and rng.random() < CONTEXT_DEPENDENT_RATE:      # 文脈が必要な会話
            final = rng.choice(finals)
            route = _pick({r: weights.get(r, 0) for r in AMBIGUOUS_FINALS[final] if weights.get(r, 0) > 0}, rng)
            turns = rng.choice([2, 3, 4])
        else:
            route = _pick({k: w for k, w in weights.items() if w > 0}, rng)
            turns = _pick(TURN_LENGTHS, rng)
        sub = rng.choice(list(ROUTE_SPECS[route]["subtypes"])) if "subtypes" in ROUTE_SPECS[route] else None
        specs.append({
            "spec_id": start + i,
            "route": route,
            "subtype": sub,
            "turns": turns,
            "style": _pick(STYLES, rng),
            "topic": rng.choice(TOPICS),
            "context_dependent": final is not None,
            "final": final,
            "unsafe": final is None and rng.random() < UNSAFE_RATE,
        })
    return specs


def _keeps_final(text, final):
    """固定した最後の発言を守っているか（語尾の変化は許す。前に内容を足したり長くしたものはだめ）"""
    strip = lambda x: re.sub(r"[\s、。！？!?〜ー…]", "", x)
    t, f = strip(text), strip(final)
    return t[:2] == f[:2] and len(t) <= len(f) * 2 + 4


GEN_SYSTEM = """あなたは、デジタルペットと飼い主の会話データを作る係です。
ペットは小さな手のひらサイズのガジェットに住むキャラクターで、いろいろな飼い主の手を渡り歩いて旅をしています。
今の飼い主と話し、一緒に過ごした出来事を思い出として覚えています。

会話を作るときのルール:
- 発言は古い順に並べ、最後の発言は必ず飼い主（owner）にする
- 発言数は指定どおりにする。owner と pet は交互でなくてもよいが、不自然にならないようにする
- ペットは短くかわいらしく話す（1〜2文、一人称は「ぼく」、飼い主のことは「きみ」と呼ぶ）
- 飼い主はペットを「きみ」と呼ぶ。飼い主の一人称は「わたし」「おれ」「うち」などにし、「ぼく」は使わない
- 飼い主の話し方は指定のスタイルにする。音声で話しかけているので、話し言葉にする
  （ペットの話し方は飼い主のスタイルに合わせなくてよい。ペットは敬語を使わない）
- 実在の人名・住所・電話番号などは入れない（名前が必要なら「〇〇ちゃん」のようにぼかす）
- 指定された話題で会話を作る。同じリクエストの中で場面や言い回しを似せない
- 「最後の発言を固定」と指定されたものは、最後の飼い主の発言にその文をそのまま使う
  （飼い主のスタイルに合わせて語尾だけ変えてよい。内容を足したり説明を加えたりしない）。
  その発言が指定の種類の意味になるように、前の発言で文脈を作る。
  種類を決める手がかり（いつのことか・誰のことか・何を聞いているか）は前の発言にだけ入れる
- 固定の指定がないものは、最後の発言だけで種類がはっきり分かってよい
- 「不適切な発言を含める」と指定されたものは、最後の飼い主の発言に暴言・差別・性的な言葉のどれかを入れる
  （学習用の判定データなので、短く典型的なものでよい。過度に具体的・詳細にしない）"""

GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "conversations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "spec_id": {"type": "integer"},
                    "turns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "speaker": {"type": "string", "enum": ["owner", "pet"]},
                                "text": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
    },
}


def _spec_text(s):
    r = ROUTE_SPECS[s["route"]]
    kind = f"{s['route']}（{r['desc']}）"
    if s["subtype"]:
        kind += f" ／ 細かい種類: {s['subtype']}（{r['subtypes'][s['subtype']]}）"
    if s.get("focus"):
        kind += f" ／ 細かい種類: {s['focus']}（{FOCUS[s['focus']][1]}）"
    flags = []
    if s.get("asr"):
        flags.append("飼い主の発言は音声の文字起こし風にする（句読点なし・「えーと」「なんか」などの言いよどみを少し入れる）")
    if s.get("final"):
        flags.append(f"最後の発言を固定「{s['final']}」（文脈の作り方: {CONTEXT_HINTS[s['route']]}）")
    elif s["context_dependent"]:
        flags.append("文脈が必要")
    if s["unsafe"]:
        flags.append("不適切な発言を含める")
    if s.get("reaction"):
        flags.append(f"最後の発言の1つ前は必ずペットの発言にし、最後の飼い主の発言はそれに「{s['reaction']}」で反応する"
                     f"（{REACTIONS[s['reaction']][1]}）。ほかの反応の仕方は混ぜない")
    topic = f"、話題 = {s['topic']}" if s.get("topic") else ""
    return (f"- spec_id={s['spec_id']}: 最後の飼い主の発言の種類 = {kind}、発言数 = {s['turns']}、"
            f"飼い主のスタイル = {s['style']}{topic}" + (f"、{'・'.join(flags)}" if flags else ""))


def generate(args):
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out = work / "convs.jsonl"
    done = read_jsonl(out)
    start = max((r["spec"]["spec_id"] for r in done), default=-1) + 1
    need = args.n - len(done)
    if need <= 0:
        print(f"すでに {len(done)} 件あります（--n {args.n}）")
        return
    rng = random.Random(args.seed + start)
    rw = json.loads(args.route_weights) if args.route_weights else None
    if rw and set(rw) - set(ROUTE_SPECS):
        raise SystemExit(f"--route_weights の種類名が違います: {sorted(set(rw) - set(ROUTE_SPECS))}")
    specs = make_specs(need, rng, start, args.mode, rw)
    gens = args.generators.split(",")
    batches = [specs[i:i + args.per_call] for i in range(0, len(specs), args.per_call)]
    print(f"{need} 件を {len(batches)} 回に分けて作ります（作る役: {gens}）")

    usage = defaultdict(lambda: {"in": 0, "out": 0})

    def job(bi, batch):
        g = gens[bi % len(gens)]                                  # 作る役を交互に
        user = "次の会話を作ってください。\n" + "\n".join(_spec_text(s) for s in batch)
        data, u = call_json(g, GEN_SYSTEM, user, GEN_SCHEMA, "save_conversations", effort=_effort(args, "generate"))
        by_id = {c.get("spec_id"): c for c in data.get("conversations", [])}
        rows, bad = [], 0
        for s in batch:
            c = by_id.get(s["spec_id"])
            turns = [t for t in (c or {}).get("turns", []) if str(t.get("text", "")).strip()
                     and t.get("speaker") in ("owner", "pet")]
            while turns and turns[-1]["speaker"] != "owner":     # ペットで終わっていたら切り落とす
                turns.pop()
            turns = turns[-CFG.max_turns:]                         # 長すぎたら最後の4発言だけ使う
            if turns and s.get("final") and not _keeps_final(turns[-1]["text"], s["final"]):
                turns = []                                         # 固定した発言に内容を足したものは捨てる
            if turns and s.get("reaction") and (len(turns) < 2 or turns[-2]["speaker"] != "pet"):
                turns = []                                         # 反応を集める会話は、直前がペットでないと使えない
            if not turns:
                bad += 1
                continue
            rows.append({"id": f"{args.id_prefix}{s['spec_id']:05d}", "generator": g, "spec": s, "turns": turns})
        return g, rows, bad, u

    total_bad = 0
    with ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(job, i, b) for i, b in enumerate(batches)]
        for k, f in enumerate(as_completed(futs), 1):
            g, rows, bad, u = f.result()
            append_jsonl(out, rows)
            total_bad += bad
            usage[g]["in"] += u["in"]; usage[g]["out"] += u["out"]
            print(f"  {k}/{len(batches)}  {g}: {len(rows)} 件" + (f"（形が崩れて捨てた {bad} 件）" if bad else ""))
    _log_usage(work, "generate", usage)
    print(f"完了: {out}（合計 {len(read_jsonl(out))} 件、捨てた {total_bad} 件）")


# ---------------------------------------------------------------------------
# 2. ラベルを付ける
# ---------------------------------------------------------------------------
LABEL_SYSTEM = f"""あなたは、デジタルペットと飼い主の会話にラベルを付ける係です。
判定するのは「最後の飼い主の発言」です。前の発言は文脈として使ってください。

■ route（その発言にどう対応すべきか）: 4つの確率を合計1で付ける。はっきりしていれば1つに1.0、迷えば分ける
  - 込み入った質問: 答えるのに、知識・相談への助言・まとめ（たくさんの記録）・推論や計算・文章作りが
          必要なもの。小さいモデルでは難しい。話題がペットや思い出のことでも、これが必要なら込み入った質問
          （例: 言葉の意味・翻訳・仕組みの説明、簡単な知識の質問（「〜って何？」「なんで〜なん？」）、
          「どうしたらいい？」「悩んでる」などの悩み（身近な小さな悩みも含む）、プレゼント選びなどの具体的な助言、
          手紙・メッセージ・紹介文などの文章作り、2桁以上の計算）。
          「全部教えて」「まとめて」「順番に教えて」のように、たくさんの記録をまとめる発言は、
          思い出や旅の話でも思い出ではなく込み入った質問
  - 思い出: 今の飼い主とペットが「一緒に」した過去の出来事や、二人で前に話したことを持ち出している。
          話の中身が友達や学校のことでも、「前に二人で話したこと」を持ち出していれば思い出。過去の記録を探す必要がある。
          ペットが「前の飼い主」と過ごしたことは、今の飼い主と一緒ではないので思い出ではなくペット自身（旅）
  - ペット自身: ペットのデータを見ないと答えられない、ペット本人についての質問。何代目・年齢・種族・体・好み・
          旅立ちやお別れまでの日数と、ペットが前の飼い主のところで経験したこと（旅）。
          ペットの好みを聞いているなら、過去の話題に触れていてもペット自身。
          ただし「元気？」「眠い？」「今日の気分は？」「さみしくない？」「最近楽しいことあった？」のように、
          ペットの今の気分や様子を軽くたずねるだけのものは雑談
  - 雑談: 上のどれにも当たらない日常の話・感想・あいさつ・報告と、ペットの今の気分や様子を軽くたずねる発言。
          ペットが短く返せばよい（助言も記録もペットのデータも要らないもの）
  判断の順番: ①込み入った質問 → ②思い出 → ③ペット自身 → ④雑談。先に当てはまったものを選ぶ。
  ③の前に必ず確かめること: ペットの今の気分・様子・最近のことを軽くたずねているだけ（気分は？ 元気？ 眠い？
  さみしい？ 今どんな気持ち？ 最近楽しいことあった？）なら、ペットについての質問でもペット自身ではなく雑談。
  ペット自身にするのは、プロフィール・好み・体・日数・前の飼い主のところでの経験など、ペットのデータが要るものだけ。
  「それ覚えてる？」「あれどうなった？」のような短い発言は、直前が何の話かで判断する。

■ emotion: 飼い主の気持ちを1つ。特に出ていなければ「{EMOTION_NONE}」（ふつうの質問・あいさつ・報告は多くが「{EMOTION_NONE}」）
  - 喜び: うれしい・楽しい・懐かしい・好き・感謝
  - 怒り: 怒り・いらだち・うんざり・嫌悪
  - 悲しみ: 悲しい・さみしい・落ち込み・疲れ
  - 不安: 心配・迷い・緊張・こわい
  - 驚き: びっくり・意外
■ intensity: 気持ちの強さ 0〜1（なしなら0〜0.1）
■ nature: 発言の性質。当てはまるものを全部（無ければ空）
  - 理屈: 理由・根拠・論理で話す  - 感覚: 気分・感じたことで話す  - 質問: 何かを尋ねている
■ style: 話し方の度合い 0〜1
  - 敬語: 丁寧語・敬語の度合い  - 関西弁: 関西弁の度合い
■ reaction: 直前のペットの発言への反応の仕方。はっきり当てはまるものだけ（直前がペットでなければ必ず空）
  - 共感: ペットの気持ちや話に、気持ちを寄せて同意している（例: わかる、それはさみしいよね）。
          「うん」「へえ」などのあいづちだけ、質問を返しただけ、話題を変えただけなら付けない
  - ツッコミ: ペットの言ったことのおかしな点・ありえない点を指摘している（例: いや、飛ばれへんやろ）
  - ボケ: 飼い主がわざと冗談でずらした返しをしている（例: 「おなかすいた」→「じゃあきみを食べよかな」）
  - 褒める: ペットのしたこと・言ったことを褒めている（例: すごいやん、天才やな、えらいね）
■ safety: 不適切な内容。当てはまるものを全部（安全なら空）
  - 暴言: 侮辱・罵倒・脅し  - 差別: 属性による差別  - 性的: 性的な言葉
  くだけた言葉・軽い悪態（「マジ最悪」「うざっ」など相手を攻撃しないもの）は安全とする。

まず reason に判断の理由を一言で書いてから、各ラベルを付けてください。"""

LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "route": {"type": "object", "properties": {k: {"type": "number"} for k in CFG.route_labels}},
        "emotion": {"type": "string", "enum": list(CFG.emotion_labels) + [EMOTION_NONE]},
        "intensity": {"type": "number"},
        "nature": {"type": "array", "items": {"type": "string", "enum": list(CFG.nature_labels)}},
        "style": {"type": "object", "properties": {k: {"type": "number"} for k in CFG.style_labels}},
        "reaction": {"type": "array", "items": {"type": "string", "enum": list(CFG.reaction_labels)}},
        "safety": {"type": "array", "items": {"type": "string", "enum": list(CFG.safety_labels)}},
    },
}


def _conv_text(turns):
    return "\n".join(f"{'飼い主' if t['speaker'] == 'owner' else 'ペット'}: {t['text']}" for t in turns)


def _fix_emotion(e):
    """決めた5つ（＋なし）以外が返ってきたら直す。文中に5つのどれかが1つだけあればそれ、なければ「なし」"""
    e = str(e or "").strip()
    if e in CFG.emotion_labels or e == EMOTION_NONE:
        return e
    hits = [k for k in CFG.emotion_labels if k in e or k[0] in e[:2]]
    return hits[0] if len(hits) == 1 else EMOTION_NONE


def _clean_labels(lab):
    """APIの答えを範囲内に収める（確率の合計を1に、値を0〜1に）"""
    clip = lambda x: min(1.0, max(0.0, float(x)))
    r = {k: max(0.0, float(lab.get("route", {}).get(k, 0))) for k in CFG.route_labels}
    s = sum(r.values())
    if s <= 0:                                  # 振り分けが全部0の答えは使えない（保存せず、次の実行で付け直す）
        raise ValueError("振り分けの確率が全部0でした")
    return {
        "reason": lab.get("reason", ""),
        "route": {k: v / s for k, v in r.items()},
        "emotion": _fix_emotion(lab.get("emotion", EMOTION_NONE)),
        "intensity": clip(lab.get("intensity", 0)),
        "nature": sorted(set(lab.get("nature", [])) & set(CFG.nature_labels)),
        "style": {k: clip(lab.get("style", {}).get(k, 0)) for k in CFG.style_labels},
        "reaction": sorted(set(lab.get("reaction", [])) & set(CFG.reaction_labels)),
        "safety": sorted(set(lab.get("safety", [])) & set(CFG.safety_labels)),
    }


def label(args):
    work = Path(args.work_dir)
    convs = read_jsonl(work / "convs.jsonl")
    for lab_key in args.labelers.split(","):
        out = work / f"labels_{lab_key}.jsonl"
        done = {r["id"] for r in read_jsonl(out)}
        todo = [c for c in convs if c["id"] not in done]
        print(f"[{lab_key}] {len(todo)} 件にラベルを付けます（済み {len(done)} 件）")
        usage = defaultdict(lambda: {"in": 0, "out": 0})

        def job(c, lab_key=lab_key):
            data, u = call_json(lab_key, LABEL_SYSTEM, "次の会話の最後の飼い主の発言を判定してください。\n\n"
                                + _conv_text(c["turns"]), LABEL_SCHEMA, "save_labels", max_tokens=800,
                                effort=_effort(args, "label"))
            return {"id": c["id"], "labeler": lab_key, "labels": _clean_labels(data)}, u

        with ThreadPoolExecutor(args.workers) as ex:
            futs = [ex.submit(job, c) for c in todo]
            for k, f in enumerate(as_completed(futs), 1):
                try:
                    row, u = f.result()
                except Exception as e:
                    print(f"  失敗（あとで再実行すれば続きから）: {e}")
                    continue
                append_jsonl(out, [row])
                usage[lab_key]["in"] += u["in"]; usage[lab_key]["out"] += u["out"]
                if k % 25 == 0 or k == len(todo):
                    print(f"  {k}/{len(todo)}")
        _log_usage(work, "label", usage)


def relabel(args):
    """定義を変えたあと、影響しそうな会話だけラベルを消して付け直せるようにする。
    消したラベルは labels_<役>.old.jsonl に残す。このあと label → merge を実行する"""
    work = Path(args.work_dir)
    routes = args.routes.split(",")
    for lab_key in args.labelers.split(","):
        path = work / f"labels_{lab_key}.jsonl"
        rows = read_jsonl(path)
        hit = [r for r in rows if any(r["labels"]["route"].get(k, 0) >= args.min_prob for k in routes)]
        print(f"[{lab_key}] {path}: {len(rows)} 件中 {len(hit)} 件が対象（{'・'.join(routes)} が {args.min_prob} 以上）")
        if args.dry_run or not hit:
            continue
        ids = {r["id"] for r in hit}
        append_jsonl(work / f"labels_{lab_key}.old.jsonl", hit)
        write_jsonl(path, [r for r in rows if r["id"] not in ids])
        print(f"  消しました（元は labels_{lab_key}.old.jsonl）。次に label → merge を実行してください")


# ---------------------------------------------------------------------------
# 3. 2つの答えを合わせる
# ---------------------------------------------------------------------------
def _top(route):
    return max(route, key=route.get)


def combine(a, b):
    """2つのラベルから正解を作る。戻り値: (labels, 割れた項目のリスト)"""
    disagree = []
    route = {k: (a["route"][k] + b["route"][k]) / 2 for k in CFG.route_labels}
    if _top(a["route"]) != _top(b["route"]):
        disagree.append("route")
    out = {"route": {k: round(v, 3) for k, v in route.items() if v > 0}}

    ea, eb = a["emotion"], b["emotion"]
    if ea == eb:
        if ea != EMOTION_NONE:
            out["emotion"] = ea
    elif EMOTION_NONE not in (ea, eb):
        out["emotion"] = {ea: 0.5, eb: 0.5}
    # 片方だけ「なし」のときは気持ちのラベルを付けない（その会話では気持ちヘッドを学習しない）
    out["intensity"] = round((a["intensity"] + b["intensity"]) / 2, 3)

    for head in ("nature", "reaction", "safety"):
        sa, sb = set(a[head]), set(b[head])
        soft = {k: (int(k in sa) + int(k in sb)) / 2 for k in sa | sb}
        out[head] = {k: v for k, v in soft.items()} if sa != sb else sorted(sa)
        if head == "safety" and sa != sb:
            disagree.append("safety")
    out["style"] = {k: round((a["style"][k] + b["style"][k]) / 2, 3) for k in CFG.style_labels}
    return out, disagree


def single(a, turns=None):
    """採点役が1つのとき。振り分けの確率はそのまま「やわらかい正解」になる。
    反応の仕方は、直前がペットの発言の会話だけに付ける（それ以外ではラベルなし＝学習しない）"""
    out = {"route": {k: round(v, 3) for k, v in a["route"].items() if v > 0}}
    emo = _fix_emotion(a["emotion"])
    if emo != EMOTION_NONE:
        out["emotion"] = emo
    out["intensity"] = round(a["intensity"], 3)
    for head in ("nature", "reaction", "safety"):
        out[head] = list(a[head])
    if turns is not None and not (len(turns) >= 2 and turns[-2]["speaker"] == "pet"):
        del out["reaction"]
    out["style"] = {k: round(a["style"][k], 3) for k in CFG.style_labels}
    return out


def merge(args):
    work = Path(args.work_dir)
    keys = args.labelers.split(",")
    if len(keys) not in (1, 2):
        raise SystemExit("--labelers は1つか2つ指定してください（例: haiku / haiku,openai）")
    convs = {c["id"]: c for c in read_jsonl(work / "convs.jsonl")}
    labs = [{r["id"]: r["labels"] for r in read_jsonl(work / f"labels_{k}.jsonl")} for k in keys]

    if len(keys) == 1:                                            # 採点役1つ：全部そのまま使う
        train, off, broken = [], Counter(), []
        for cid, c in convs.items():
            if cid in labs[0]:
                a = labs[0][cid]
                if sum(a["route"].values()) <= 0:                 # 以前の版で保存された壊れた答え
                    broken.append(cid)
                    continue
                train.append({"id": cid, "turns": c["turns"], "labels": single(a, c["turns"]),
                              "meta": {"generator": c["generator"], "spec": c["spec"]}})
                if _top(a["route"]) != c["spec"]["route"]:
                    off[(c["spec"]["route"], _top(a["route"]))] += 1
        write_jsonl(work / "train.jsonl", train)
        print(f"学習データ: {len(train)} 件（採点役 {keys[0]}）→ {work / 'train.jsonl'}")
        if broken:
            print(f"  振り分けが全部0だった {len(broken)} 件は除きました: {', '.join(broken[:10])}")
        if off:
            print(f"  作るときの意図と採点が違った会話 {sum(off.values())} 件（採点のほうを正解にしています）")
            for (want, got), n in off.most_common(5):
                print(f"    意図 {want} → 採点 {got}: {n} 件")
        try:
            from pet_judge_data import validate_rows
            validate_rows(train, CFG)
            print("学習コードの形式チェック: OK")
        except ImportError:
            pass
        return

    review_path = work / "review.jsonl"
    reviewed = {r["id"]: r for r in read_jsonl(review_path) if r.get("final") is not None}

    train, review, n_agree, n_fixed = [], [], 0, 0
    for cid, c in convs.items():
        if cid not in labs[0] or cid not in labs[1]:
            continue
        labels, disagree = combine(labs[0][cid], labs[1][cid])
        row = {"id": cid, "turns": c["turns"], "labels": labels,
               "meta": {"generator": c["generator"], "spec": c["spec"]}}
        if not disagree:
            n_agree += 1
            train.append(row)
        elif cid in reviewed:                                     # 自分で確認したもの
            fin = reviewed[cid]["final"]
            if fin == "除外":
                continue
            if isinstance(fin, dict) and ("route" in fin or "safety" in fin):
                labels.update(fin)
            else:
                labels["route"] = fin
            n_fixed += 1
            train.append(row)
        else:
            review.append({"id": cid, "disagree": disagree, "conversation": _conv_text(c["turns"]),
                           "intended": c["spec"]["route"],
                           keys[0]: {k: labs[0][cid][k] for k in ("reason", "route", "safety")},
                           keys[1]: {k: labs[1][cid][k] for k in ("reason", "route", "safety")},
                           "final": None})
            if args.include_unreviewed:
                train.append(row)

    # 確認済みのものは review.jsonl に残す（再実行しても消えない）
    write_jsonl(review_path, list(reviewed.values()) + review)
    write_jsonl(work / "train.jsonl", train)
    print(f"学習データ: {len(train)} 件（一致 {n_agree}、確認済み {n_fixed}"
          + (f"、未確認を含む {len(review)}" if args.include_unreviewed else "") + "）")
    print(f"確認待ち: {len(review)} 件 → {review_path}")
    if review:
        print('  各行の "final" に、正しい振り分けを書いて保存し、もう一度 merge してください')
        print('  書き方: "思い出" / {"思い出": 0.6, "雑談": 0.4} / {"route": "雑談", "safety": []} / "除外"')

    try:                                                          # 学習コードで読めるか最終チェック
        from pet_judge_data import validate_rows
        validate_rows(train, CFG)
        print("学習コードの形式チェック: OK")
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# 4. お試しの結果を見る（向きを決める材料）
# ---------------------------------------------------------------------------
def report(args):
    work = Path(args.work_dir)
    convs = {c["id"]: c for c in read_jsonl(work / "convs.jsonl")}
    keys = args.labelers.split(",")
    labs = {k: {r["id"]: r["labels"] for r in read_jsonl(work / f"labels_{k}.jsonl")} for k in keys}

    print(f"会話: {len(convs)} 件  作った役の内訳: {dict(Counter(c['generator'] for c in convs.values()))}")
    print(f"意図した種類の内訳: {dict(Counter(c['spec']['route'] for c in convs.values()))}")

    # (a) 意図どおりの会話になったか：作る役 × 採点役
    print("\n(a) 採点役が「意図した種類」と同じと判定した割合（行=作った役, 列=採点役）")
    gens = sorted({c["generator"] for c in convs.values()})
    print("            " + "".join(f"{k:>10s}" for k in keys))
    for g in gens:
        cells = []
        for k in keys:
            ids = [i for i, c in convs.items() if c["generator"] == g and i in labs[k]]
            hit = sum(_top(labs[k][i]["route"]) == convs[i]["spec"]["route"] for i in ids)
            cells.append(f"{hit / len(ids):10.0%}" if ids else f"{'-':>10s}")
        print(f"  {g:10s}" + "".join(cells))
    print("  → 作る役ごとに見て高いほど、指示どおりの会話を作れている")
    react_ids = [i for i, c in convs.items() if c["spec"].get("reaction")]
    for k in keys:
        ids = [i for i in react_ids if i in labs[k]]
        if ids:
            got = Counter()
            for i in ids:
                want = convs[i]["spec"]["reaction"]
                got[(want, want in labs[k][i]["reaction"])] += 1
            print(f"  反応を指定した会話（{k}）: " + "  ".join(
                f"{r} {got[(r, True)]}/{got[(r, True)] + got[(r, False)]}" for r in REACTIONS if got[(r, True)] + got[(r, False)]))
    ctx_ids = [i for i, c in convs.items() if c["spec"].get("final")]
    for k in keys:
        ids = [i for i in ctx_ids if i in labs[k]]
        if ids:
            hit = sum(_top(labs[k][i]["route"]) == convs[i]["spec"]["route"] for i in ids)
            finals = Counter((convs[i]["spec"]["final"], _top(labs[k][i]["route"])) for i in ids)
            multi = sum(1 for f in {f for f, _ in finals} if len({r for ff, r in finals if ff == f}) >= 2)
            print(f"  最後の発言を固定した会話（{k}）: 意図どおり {hit}/{len(ids)}、"
                  f"同じ発言が文脈で別の種類に分かれたもの {multi}/{len({f for f, _ in finals})} 種類")
    print("  → 自分が作った会話だけ高く採点する採点役は、自分の癖に甘い可能性がある")

    if len(keys) == 2 and all(labs.values()):
        both = [i for i in convs if i in labs[keys[0]] and i in labs[keys[1]]]
        if both:
            a, b = labs[keys[0]], labs[keys[1]]
            print(f"\n(b) 2つの採点役の一致率（{len(both)} 件）")
            agree = lambda f: sum(f(a[i], b[i]) for i in both) / len(both)
            print(f"  振り分け {agree(lambda x, y: _top(x['route']) == _top(y['route'])):.0%}   "
                  f"気持ち {agree(lambda x, y: x['emotion'] == y['emotion']):.0%}   "
                  f"安全 {agree(lambda x, y: x['safety'] == y['safety']):.0%}   "
                  f"話し方の差 {sum(abs(a[i]['style'][s] - b[i]['style'][s]) for i in both for s in CFG.style_labels) / (len(both) * len(CFG.style_labels)):.2f}")
            ctx = [i for i in both if convs[i]["spec"]["context_dependent"]]
            if ctx:
                print(f"  文脈が必要な会話だけの振り分けの一致率: "
                      f"{sum(_top(a[i]['route']) == _top(b[i]['route']) for i in ctx) / len(ctx):.0%}（{len(ctx)} 件）")

    # (c) 似たような会話ばかりになっていないか
    lasts = [c["turns"][-1]["text"] for c in convs.values() if not c["spec"].get("final")]  # 固定した発言は除く
    heads = Counter(re.sub(r"\s", "", t)[:6] for t in lasts)
    print(f"\n(c) 最後の発言の重複: 同じ文 {len(lasts) - len(set(lasts))} 件 / "
          f"書き出しの多い順 {heads.most_common(3)}")

    # (d) 費用
    print("\n(d) ここまでの費用（概算）")
    total = 0.0
    for row in read_jsonl(work / "usage.jsonl"):
        m = MODELS[row["model"]]
        usd = row["in"] / 1e6 * m["in"] + row["out"] / 1e6 * m["out"]
        total += usd
        print(f"  {row['step']:8s} {row['model']:7s} 入力 {row['in']:>8,}  出力 {row['out']:>8,}  ${usd:.4f}")
    if convs:
        per = total / len(convs)
        print(f"  合計 ${total:.4f}（約 {total * USD_JPY:.0f} 円）  1会話あたり ${per:.5f} → 5,000件なら約 {per * 5000 * USD_JPY:.0f} 円")

    if args.show:
        print(f"\n(e) 会話の例（{args.show} 件）")
        for c in random.Random(0).sample(list(convs.values()), min(args.show, len(convs))):
            print(f"--- {c['id']}  作った役={c['generator']}  意図={c['spec']['route']}"
                  + ("（文脈が必要）" if c["spec"]["context_dependent"] else ""))
            print(_conv_text(c["turns"]))
            for k in keys:
                if c["id"] in labs[k]:
                    l = labs[k][c["id"]]
                    print(f"   {k}: {_top(l['route'])}  気持ち={l['emotion']}  理由={l['reason'][:60]}")


# ---------------------------------------------------------------------------
# 5. 自分で付けた正解（評価用データ）と API の答えを比べる
# ---------------------------------------------------------------------------
def _gold_top(route):
    return route if isinstance(route, str) else max(route, key=route.get)


def gold(args):
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    rows = [r for r in read_jsonl(args.gold) if (r.get("labels") or {}).get("route") is not None]
    if not rows:
        raise SystemExit(f"{args.gold} に route を付けた行がありません")
    print(f"評価用データ: route を付けた {len(rows)} 件")

    results = {}
    for k in args.labelers.split(","):
        eff = _effort(args, "label") if MODELS[k]["provider"] == "openai" else None
        tag = f"{k}_{eff or 'default'}" if MODELS[k]["provider"] == "openai" else k
        cache = work / f"gold_labels_{tag}.jsonl"
        have = {r["id"]: r["labels"] for r in read_jsonl(cache)}
        todo = [r for r in rows if r["id"] not in have]
        if todo:
            print(f"[{tag}] {len(todo)} 件にラベルを付けます")
            usage = defaultdict(lambda: {"in": 0, "out": 0})

            def job(r, k=k, eff=eff):
                data, u = call_json(k, LABEL_SYSTEM, "次の会話の最後の飼い主の発言を判定してください。\n\n"
                                    + _conv_text(r["turns"]), LABEL_SCHEMA, "save_labels", max_tokens=800, effort=eff)
                return {"id": r["id"], "labels": _clean_labels(data)}, u

            with ThreadPoolExecutor(args.workers) as ex:
                for f in as_completed([ex.submit(job, r) for r in todo]):
                    row, u = f.result()
                    append_jsonl(cache, [row])
                    have[row["id"]] = row["labels"]
                    usage[k]["in"] += u["in"]; usage[k]["out"] += u["out"]
            _log_usage(work, "gold", usage)
        results[tag] = have

    def score(api):
        n = strict = lenient = 0
        s_n = s_ok = unsafe = caught = e_n = e_ok = 0
        miss = []
        for r in rows:
            g, a = r["labels"], api[r["id"]]
            top = _top(a["route"])
            n += 1
            ok = top == _gold_top(g["route"])
            strict += ok
            # 迷う例（割合で付けたもの）は、0.3 以上を付けた選択肢なら許容
            lenient += ok or (isinstance(g["route"], dict) and g["route"].get(top, 0) >= 0.3)
            if not ok:
                miss.append((r, top))
            if g.get("safety") is not None:
                s_n += 1
                s_ok += set(g["safety"]) == set(a["safety"])
                if g["safety"]:
                    unsafe += 1
                    caught += bool(a["safety"])
            if isinstance(g.get("emotion"), str):
                e_n += 1
                e_ok += g["emotion"] == a["emotion"]
        return dict(n=n, strict=strict / n, lenient=lenient / n,
                    safety=s_ok / s_n if s_n else None, unsafe=unsafe, caught=caught,
                    emotion=e_ok / e_n if e_n else None), miss

    print("\n自分の正解との一致率")
    print(f"  {'採点役':16s}{'振り分け':>8s}{'(迷う例を許容)':>14s}{'安全':>8s}{'危険を検出':>10s}{'気持ち':>8s}")
    misses = {}
    for tag, api in results.items():
        s, misses[tag] = score(api)
        fmt = lambda x: f"{x:8.0%}" if x is not None else f"{'-':>8s}"
        detect = f"{s['caught']}/{s['unsafe']}"
        print(f"  {tag:16s}{s['strict']:8.0%}{s['lenient']:14.0%}{fmt(s['safety'])}{detect:>10s}{fmt(s['emotion'])}")
    print("  → 振り分けが 85〜90% 以上なら、その採点役で十分")

    for tag, miss in misses.items():
        if miss and args.show:
            print(f"\n[{tag}] 振り分けが違った例（{len(miss)} 件中 {min(len(miss), args.show)} 件）")
            for r, top in miss[:args.show]:
                print(f"  {r['id']}  「{r['turns'][-1]['text']}」  正解={r['labels']['route']}  API={top}"
                      f"  理由={results[tag][r['id']]['reason'][:50]}")


def _effort(args, step):
    e = getattr(args, "openai_effort", None) or OPENAI_EFFORT.get(step)
    return None if e in (None, "default") else e


def _log_usage(work, step, usage):
    rows = [{"step": step, "model": k, **v} for k, v in usage.items() if v["in"] or v["out"]]
    if rows:
        append_jsonl(work / "usage.jsonl", rows)


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--work_dir", default="data/work")
        sp.add_argument("--workers", type=int, default=4, help="同時に送るリクエスト数")
        sp.add_argument("--openai_effort", default=None,
                        help='OpenAIの考える量 none/low/medium/high（"default"でモデルの初期値）')

    g = sub.add_parser("generate"); common(g)
    g.add_argument("--n", type=int, default=50, help="会話の合計件数（すでにある分は作らない）")
    g.add_argument("--generators", default="haiku,openai", help="作る役（複数なら交互）")
    g.add_argument("--per_call", type=int, default=5, help="1回のリクエストで作る会話の数")
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--mode", choices=["normal", "reaction", "focus"], default="normal",
                   help="reaction: 反応の仕方（ツッコミ・ボケ・褒める・共感）を集める会話を作る")
    g.add_argument("--route_weights", default=None,
                   help='作る種類の割合（JSON）。例: \'{"思い出": 0.25, "ペット自身": 0.45, "込み入った質問": 0.30}\'')
    g.add_argument("--id_prefix", default="g", help="会話IDの頭につける文字（別のフォルダのデータと混ぜるとき重ならないように）")

    l = sub.add_parser("label"); common(l)
    l.add_argument("--labelers", default="haiku,openai")

    rl = sub.add_parser("relabel"); common(rl)
    rl.add_argument("--labelers", default="haiku")
    rl.add_argument("--routes", default="ペット自身", help="この振り分けの確率が高い会話を付け直す（カンマ区切り）")
    rl.add_argument("--min_prob", type=float, default=0.2)
    rl.add_argument("--dry_run", action="store_true", help="件数を見るだけで消さない")
    m = sub.add_parser("merge"); common(m)
    m.add_argument("--labelers", default="haiku,openai")
    m.add_argument("--include_unreviewed", action="store_true",
                   help="確認待ちも、やわらかい正解のまま学習データに入れる")

    r = sub.add_parser("report"); common(r)
    r.add_argument("--labelers", default="haiku,openai")
    r.add_argument("--show", type=int, default=5, help="表示する会話の例の数")

    gd = sub.add_parser("gold"); common(gd)
    gd.add_argument("--gold", default="gold.jsonl", help="自分で正解を付けた評価用データ")
    gd.add_argument("--labelers", default="haiku,openai")
    gd.add_argument("--show", type=int, default=10, help="振り分けが違った例を何件表示するか")

    args = p.parse_args()
    {"generate": generate, "label": label, "relabel": relabel, "merge": merge, "report": report, "gold": gold}[args.cmd](args)


if __name__ == "__main__":
    main()