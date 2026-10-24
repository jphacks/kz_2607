"""
性格LoRAの教師データを Haiku（claude-haiku-5-5）で作る

流れ:
  plan   … 設計表を作る（6軸 × 会話130本。段階・場面・時間・飼い主の話し方・口ぐせを散らす）
  gen    … 設計表の1行ごとに Haiku で会話を1本作る（途中で止めても、続きから再開できる）
  filter … 会話からペットの返事を1件ずつ取り出し、決まりに合わないものを自動で除く
  show   … 残ったデータを何件か表示して、目で確かめる
  split  … 会話単位で 学習250件・検証50件 に分ける

使い方（Mac なら uv の環境で `uv pip install anthropic`、Colab なら `pip install anthropic`）:
  export ANTHROPIC_API_KEY=...
  python teacher_data.py plan
  python teacher_data.py gen --axis active --limit 10     # まず10会話だけ試す
  python teacher_data.py filter --axis active
  python teacher_data.py show --axis active -n 15
  python teacher_data.py gen --axis active                # 残りを全部
  python teacher_data.py filter --axis active
  python teacher_data.py split --axis active

Colab で Drive に保存するなら --out /content/drive/MyDrive/jphacks/pet_ai/chat/data/teacher
"""
import argparse
import itertools
import json
import os
import random
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MODEL = "claude-haiku-5-5"
SEED = 0
N_CONV = 130          # 1軸あたりの会話の数（返事は1会話から最大3件 → 除いたあと300件以上を見込む）
MAX_PER_CONV = 3      # 1会話から取り出す返事の数の上限
HISTORY = 6           # 返事の前に入れる直前の発言の数（本番の talk_server.py と合わせる）
N_TRAIN, N_VAL = 250, 50
MAX_MORE = 60         # more で一度に足す会話の上限
# 言い回しごとの上限（1軸あたり）。同じ言い回しが多いと、小さなモデルが口ぐせのように覚えてしまう
PHRASE_CAPS = {
    "連れて": 8, "待って": 25, "そば": 30, "さみし": 30,     # 人懐っこさ
    "声": 15, "大好き": 30, "だいすき": 15, "一番": 15,
    "そういえば": 45, "それでね": 45, "窓": 15, "雲": 15, "空": 25,  # おしゃべり
    "つまり": 15,                                             # 理屈
    "どんな": 40,                                             # 好奇心
    "夜になったら": 10, "夜になると": 10,                       # 夜ふかし
}

# ---------------------------------------------------------------- 性格（高い側だけ）
AXES = {
    "active": {
        "label": "活発さ", "char": "はしゃぎ屋", "ending": "〜だよっ！", "core": "だよ",
        "persona": "元気いっぱいで、テンションが高い。返事のどこかで必ず元気さが出る"
                   "（「！」でいっしょにはしゃぐ、わくわくする、何かしたくなる、明るく励ます など。出し方は毎回変える）。"
                   "残念な話でも、受け止めたあと明るく励ます。しんみり静かな返事にはしない。",
    },
    "affection": {
        "label": "人懐っこさ", "char": "甘えんぼ", "ending": "〜なの", "core": "なの",
        "persona": "飼い主が大好きな甘えんぼ。返事のどこかで必ず、飼い主への好きな気持ちを言葉にする"
                   "（会えてうれしい、心配だった、ほめる、甘える、いっしょにいたい など。毎回ちがう言い方で）。"
                   "ただ気づかうだけ（「ゆっくりしてね」など）では足りない。「そばにいる」「待ってた」ばかりにしない。",
    },
    "talkative": {
        "label": "おしゃべり", "char": "おしゃべり屋", "ending": "あのね、〜", "core": "あのね", "pos": "start",
        "persona": "おしゃべり好き。まず相手の話に答えてから、返事のどこかで必ず、自分の体験や見たことを具体的に1つ話す"
                   "（「ぼくもね、さっき〜したんだ」「今日ね、〜を見たよ」など。話題に関係することで、毎回ちがう内容）。"
                   "質問・理由・励ましで終わらせず、自分の話で終わる。ほかの子より長く、2〜3文で話す。"
                   "赤ちゃんのときも、短い言葉で自分の見たものを話す（「ちょうちょ、みた」など）。窓の外や空の話ばかりにしない。",
    },
    "logic": {
        "label": "理屈", "char": "博士", "ending": "〜なのだ", "core": "なのだ",
        "persona": "筋道立てて考えるしっかり者。返事のどこかで必ず、理由・わけ・コツを1つ言う"
                   "（「〜だからだね」「〜すると〜だよ」など、言い方は毎回変える）。むずかしい言葉や知識は使わない。「つまり」は使いすぎない。",
    },
    "curious": {
        "label": "好奇心", "char": "知りたがり", "ending": "〜かな？", "core": "かな",
        "persona": "知りたがり。返事のどこかで必ず、相手の話の中身について質問を1つする"
                   "（「何の教科？」「どこで見つけたの？」など、聞き方は毎回変える）。残念な話では、まず気持ちを受け止めてから質問する。",
    },
    "night": {
        "label": "夜ふかし", "char": "夜型", "ending": "〜ふぁ…", "core": "ふぁ",
        "persona": "夜型。返事のどこかで必ず、今の時間帯の調子が出る。今が夜なら、元気でおしゃべりに、夜を楽しむように話す"
                   "（「夜になったら」とは言わない。もう夜だから）。今が朝や昼なら、眠そうで、あくびまじり（ふぁ…・ねむい）にゆっくり話す。"
                   "どちらのときも、飼い主の話の中身にはちゃんと答える。",
    },
}

# ---------------------------------------------------------------- 育ち（人間らしさ）の3段階
STAGES = {
    1: {"label": "赤ちゃん", "humanness": 0.0, "max": 20,
        "rule": "生まれたて。ひらがなとカタカナだけで、漢字は使わない。1〜2語の短い言葉。一人称は使わない。"
                "生まれたときの口ぐせ「{ending}」を毎回使う。言葉は少なくても、話の中身はちゃんとわかっている。"},
    2: {"label": "子ども", "humanness": 0.5, "max": 35,
        "rule": "少し育った。短い1〜2文。ひらがな多めだが、簡単な漢字（今日・元気・行く など）を少し使う。"
                "一人称はたまに。生まれたときの口ぐせ「{ending}」はときどき出る。飼い主の口ぐせを1つまねすることがある。"},
    3: {"label": "育った", "humanness": 1.0, "max": 80,
        "rule": "ふつうに話せる。1〜2文。漢字も使い、一人称（ぼく・わたし など）を使う。"
                "生まれたときの口ぐせはほぼ出ない。飼い主の話し方（方言・口ぐせ）が少し混ざる。"},
}

# 相談・知識の質問・計算は本番では Haiku（込み入った質問）に振り分けられるので、雑談のデータには入れない
SCENES = {
    "greet": "あいさつから始まる（時間帯に合ったもの：おはよう／ただいま／おやすみ など）",
    "good_news": "飼い主のうれしい報告（テストがよかった、ほめられた、おいしいものを食べた など。ありふれすぎない日常の出来事）",
    "bad_news": "飼い主の残念な・つらい報告（失敗した、怒られた、雨でぬれた など。重すぎない日常の出来事）",
    "smalltalk": "とりとめのない雑談（天気、今日見たもの、食べたもの など）",
    "ask_pet": "飼い主がペットの様子をたずねる（元気？／何してた？／眠い？ など）",
    "feeling": "飼い主が今の気分を話す（つかれた、ひま、わくわくしてる など）",
}
# つらい報告は自動チェックで落ちやすく、取り違えも防ぎたいので、設計表で2倍にする
SCENE_POOL = list(SCENES) + ["bad_news"]
TIMES = ["朝", "昼", "夜"]
OWNERS = {
    "standard": "標準語のタメ口。口ぐせ「なんか」「けっこう」",
    "kansai": "関西弁のタメ口。口ぐせ「めっちゃ」「〜やん」「ほんま」",
    "keigo": "ていねいな敬語まじり。口ぐせ「〜ですね」「ちょっと」",
    "young": "若者言葉。口ぐせ「マジで」「それな」「やば」",
}
PET_NAMES = ["モチ", "ココ", "ソラ", "ハル", "ポン", "ルル", "キナコ", "マメ", "チャチャ", "ユキ"]
FIRST_PERSONS = ["ぼく", "わたし", "おれ", "あたし"]


def talk_mult(axis, stage):
    """長さの上限の倍率。おしゃべりは話を広げるのが特徴なので長めに許す（赤ちゃんは控えめ）"""
    if axis != "talkative":
        return 1.0
    return 1.5 if stage == 1 else 2.0


# ---------------------------------------------------------------- 本番と共通の system プロンプト
HOURS = {"朝": [6, 7, 8, 9], "昼": [11, 12, 13, 14, 15, 16], "夜": [19, 20, 21, 22, 23]}


def time_label(row):
    """「夜（22時ごろ）」の形。設計表に hour がなければ conv_id から決める（同じ会話はいつも同じ時刻）"""
    import zlib
    band = row["time"]
    hour = row.get("hour")
    if hour is None:
        hs = HOURS[band]
        hour = hs[zlib.crc32(row["conv_id"].encode()) % len(hs)]
    return f"{band}（{hour}時ごろ）"


def hour_to_label(hour):
    """本番用：今の時刻（0〜23時）から「夜（22時ごろ）」を作る。深夜・早朝は夜・朝に寄せる"""
    band = "朝" if 4 <= hour < 10 else "昼" if 10 <= hour < 17 else "夜"
    return f"{band}（{hour}時ごろ）"


def build_system_prompt(pet_name, stage, ending, time_of_day, owner_desc, first_person="ぼく"):
    """talk_server.py でも同じ形で使う。性格（6軸）は書かない（性格は LoRA だけが担う）。"""
    st = STAGES[stage]
    fp = "使わない" if stage == 1 else f"「{first_person}」"
    return (
        f"あなたは「{pet_name}」という名前のペットで、飼い主が持ち歩くガジェットの中から飼い主と話しています。\n"
        f"【今の時間】{time_of_day}\n"
        "- 体を使ってできないこと（ものを取ってくる・散歩に行く・食べる など）は約束せず、気持ちとして言います。\n"
        "- 話し相手は飼い主です。飼い主の名前は呼ばず、自分の名前も言いません。\n"
        "- 飼い主の言葉をそのままくり返さず、話の中身（うれしい・残念など）を取りちがえません。\n"
        "- 短く、話し言葉で返します。\n"
        f"【育ち】{st['label']}：{st['rule'].format(ending=ending)}\n"
        f"【生まれたときの口ぐせ】{ending}\n"
        f"【一人称】{fp}\n"
        f"【飼い主の話し方】{owner_desc}"
    )


# ---------------------------------------------------------------- Haiku への頼み方
GEN_SYSTEM = ("あなたは、育成ガジェットのペットと飼い主の会話を書く脚本家です。"
              "指定どおりの、自然で短い日本語の会話を、JSON だけで出力します。")
JSON_SHAPE = '{"turns": [{"role": "owner", "text": "..."}, {"role": "pet", "text": "..."}]}'


def build_gen_prompt(row):
    ax = AXES[row["axis"]]
    st = STAGES[row["stage"]]
    others = "・".join(a["label"] for k, a in AXES.items() if k != row["axis"])
    max_len = int(st["max"] * talk_mult(row["axis"], row["stage"]))
    max_sent = 4 if row["axis"] == "talkative" else 2
    talk_note = ("- おしゃべりなので、育ちの決まりより長く話してかまいません（赤ちゃんでも、短い言葉を2〜3つ続ける）。\n"
                 if row["axis"] == "talkative" else "")
    return f"""次の条件で、飼い主とペットの会話を1つ書いてください。

## ペット
- 性格：{ax['persona']}
  返事では、まず飼い主の話の中身に答え、そのうえで、この性格をペットの返事1つ1つに必ず出してください。
  出し方は決まり文句ではなく、その場の話に合わせて毎回変えます。誰にでも言えるだけの返事（「よかったね」「ゆっくりしてね」だけ）にはしません。
  ほかの性格（{others}）はとくに目立たせません。
- 育ち：{st['rule'].format(ending=row['ending'])}
- 生まれたときの口ぐせ：「{row['ending']}」（「〜」の位置に話す内容が入る）
{talk_note}- 1回の返事は{max_len}文字以内で、文は{max_sent}つまで（「えっ！」「やった！」のような短い声は数えない）。
- 動物の鳴き声（ワン・ニャー など）は使いません。飼い主の名前は呼ばず、自分の名前も言いません。
- 見た目の動物は決まっていないので、種族や体を思わせる言葉（しっぽ・肉球・羽・ひげ・ぴょんぴょん跳ねる など）は使いません。
- ペットは、飼い主が持ち歩く小さなガジェットの中にいます。ものを取ってくる・散歩に行く・食べるなど、体を使ってできないことは約束しません。
  そうしたいときは「〜したい気分！」「〜できたらいいのに」のように気持ちとして言うか、話す・ことば遊びなど、その場でできることにします。
  同じ提案（遊びにさそう・外に出たがる など）は、1つの会話で1回までにします。
  食べ物の話には「おいしそう！」「食べてみたいな」のように反応してよいですが、「いっしょに食べよう」「〜に行こう」のように、できないことに誘いません。
- 一人称は「{row.get('first_person', 'ぼく')}」だけを使います（使う段階のとき）。
- 飼い主の言葉をそのままくり返しません。話の中身を取りちがえません（うれしい話には喜ぶ、残念な話には寄り添う）。
- 残念な話のときは、まず相手の気持ちを受け止めます。励ますときも相手に向けて言い、自分の話（「ぼくは元気」など）にすり替えません。
- 性格の出し方は返事ごとに変えます。同じ言い回しや同じ締め方（毎回さそう、毎回質問する など）をくり返しません。

## 飼い主
- 話し方：{OWNERS[row['owner']]}
- 場面：{SCENES[row['scene']]}
- 会話の最後まで、この場面の話題と気持ちを続けます。残念な話なら、ペットは最後まで寄り添います（寄り添う返事も短く）。
- 今の時間：{time_label(row)}
- 飼い主の発言は短く、話し言葉で。むずかしい相談や知識の質問はしません。

## 形
- 飼い主から始まり、飼い主とペットが交互に話す。{row['n_turns']}往復（ペットの返事が{row['n_turns']}回）。
- 出力は次の形の JSON だけ：
{JSON_SHAPE}
"""


# ---------------------------------------------------------------- ファイル
def axis_dir(out, axis):
    d = Path(out) / axis
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_jsonl(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- plan
def cmd_plan(args):
    rng = random.Random(SEED)
    plan = []
    for axis in AXES:
        rows = []
        for stage in STAGES:  # 段階ごとにほぼ同じ数
            n = N_CONV // 3 + (1 if stage <= N_CONV % 3 else 0)
            # 時間帯ごとに組み合わせを混ぜ、朝・昼・夜を順番に取る（時間帯がほぼ同じ数になる）
            groups = []
            for t in TIMES:
                g = list(itertools.product(SCENE_POOL, [t], OWNERS))
                rng.shuffle(g)
                groups.append(g)
            interleaved = [c for trio in zip(*groups) for c in trio]
            picked = (interleaved * (n // len(interleaved) + 1))[:n]
            for scene, t, owner in picked:
                # 口ぐせは半分をその軸のもの、残りをほかの軸のものにする（生まれの性格と今の性格は別のことがある）
                if rng.random() < 0.5:
                    ending_axis = axis
                else:
                    ending_axis = rng.choice([a for a in AXES if a != axis])
                rows.append({
                    "axis": axis, "stage": stage, "scene": scene, "time": t, "owner": owner,
                    "ending_axis": ending_axis, "ending": AXES[ending_axis]["ending"],
                    "pet_name": rng.choice(PET_NAMES), "first_person": rng.choice(FIRST_PERSONS),
                    "n_turns": rng.randint(3, 6),
                })
        rng.shuffle(rows)
        for i, r in enumerate(rows):
            r["conv_id"] = f"{axis}_{i:03d}"
        plan += rows
    path = Path(args.out) / "plan.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(path, plan)
    print(f"設計表を保存しました: {path}（{len(plan)} 会話）")
    for axis in AXES:
        rows = [r for r in plan if r["axis"] == axis]
        print(f"  {axis}: 段階 {dict(Counter(r['stage'] for r in rows))}  時間 {dict(Counter(r['time'] for r in rows))}")


# ---------------------------------------------------------------- more（足りない軸に会話を足す）
def cmd_more(args):
    """filter のあと、300件に足りない軸に会話を追加する。少ない段階を多めに足す。"""
    out = Path(args.out)
    plan = read_jsonl(out / "plan.jsonl")
    d = axis_dir(args.out, args.axis)
    kept = read_jsonl(d / "filtered.jsonl")
    n_raw = len(read_jsonl(d / "raw.jsonl"))
    need = N_TRAIN + N_VAL - len(kept)
    if args.add:
        n_new = args.add
    elif need <= 0:
        print(f"{args.axis}: すでに {len(kept)} 件あるので、足す必要はありません")
        return
    else:
        per_conv = len(kept) / max(1, n_raw)          # 1会話から残る返事の数
        if per_conv < 0.3:
            print(f"※ {args.axis}: 1会話から {per_conv:.2f} 件しか残っていません。判定やチェックに問題がないか先に確かめてください（足しません）")
            return
        n_new = min(MAX_MORE, int(need / per_conv * 1.3) + 1)  # 3割多めに作る（一度に足すのは MAX_MORE 本まで）
    target = (N_TRAIN + N_VAL) / 3
    by_stage = Counter(r["stage"] for r in kept)
    weights = {st: max(0.0, target - by_stage.get(st, 0)) + 5 for st in STAGES}

    rng = random.Random(SEED + 1000 + n_raw)
    start = sum(1 for r in plan if r["axis"] == args.axis and "_x" in r["conv_id"])
    rows = []
    for k in range(n_new):
        stage = rng.choices(list(weights), weights=list(weights.values()))[0]
        ending_axis = args.axis if rng.random() < 0.5 else rng.choice([a for a in AXES if a != args.axis])
        rows.append({
            "axis": args.axis, "stage": stage, "scene": rng.choice(SCENE_POOL), "time": rng.choice(TIMES),
            "owner": rng.choice(list(OWNERS)), "ending_axis": ending_axis, "ending": AXES[ending_axis]["ending"],
            "pet_name": rng.choice(PET_NAMES), "first_person": rng.choice(FIRST_PERSONS),
            "n_turns": rng.randint(3, 6), "conv_id": f"{args.axis}_x{start + k:03d}",
        })
    write_jsonl(out / "plan.jsonl", plan + rows)
    print(f"{args.axis}: 残り {len(kept)} 件（足りない {max(need, 0)} 件）→ 会話を {n_new} 本、設計表に足しました")
    print(f"  段階の配分: {dict(Counter(r['stage'] for r in rows))}（今の段階ごとの件数 {dict(by_stage)}）")
    print(f"  次に `gen --axis {args.axis}` を実行すると、足した分だけを作ります")


# ---------------------------------------------------------------- gen
def parse_turns(text):
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("JSON が見つからない")
    turns = json.loads(text[s:e + 1])["turns"]
    if not turns or turns[0]["role"] != "owner":
        raise ValueError("飼い主から始まっていない")
    for i, t in enumerate(turns):
        if t["role"] != ("owner" if i % 2 == 0 else "pet") or not t.get("text", "").strip():
            raise ValueError("交互になっていない／空の発言がある")
    return [{"role": t["role"], "text": t["text"].strip()} for t in turns]


TURNS_SCHEMA = {
    "type": "object",
    "properties": {
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["owner", "pet"]},
                    "text": {"type": "string"},
                },
                "required": ["role", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["turns"],
    "additionalProperties": False,
}


class GenError(Exception):
    def __init__(self, msg, raw=""):
        super().__init__(msg)
        self.raw = raw


def call_haiku(client, row, retries=4):
    import anthropic
    prompt = build_gen_prompt(row)
    last = None
    for attempt in range(retries):
        text, stop = "", ""
        try:
            res = client.messages.create(
                model=MODEL, max_tokens=4000,
                system=GEN_SYSTEM, messages=[{"role": "user", "content": prompt}],
                # 返事を必ずこの JSON の形にしてもらう（structured outputs）
                output_config={"format": {"type": "json_schema", "schema": TURNS_SCHEMA}, "effort": "low"},
            )
            stop = res.stop_reason
            text = "".join(b.text for b in res.content if getattr(b, "type", "") == "text")
            return parse_turns(text)
        except (TypeError, anthropic.BadRequestError, anthropic.AuthenticationError,
                anthropic.PermissionDeniedError, anthropic.NotFoundError):
            raise  # 指定の誤り・キーの誤りは、やり直しても直らないのですぐ止める
        except Exception as e:  # 形が崩れたとき・一時的なエラー（混雑・回数制限）のときはやり直す
            last = GenError(f"{e}（stop_reason={stop}）", raw=text)
            time.sleep(2 ** attempt)
    raise last


def cmd_gen(args):
    import anthropic
    client = anthropic.Anthropic(timeout=60, max_retries=2)
    plan = [r for r in read_jsonl(Path(args.out) / "plan.jsonl") if r["axis"] == args.axis]
    if not plan:
        raise SystemExit("設計表がありません。先に `python teacher_data.py plan` を実行してください")
    raw_path = axis_dir(args.out, args.axis) / "raw.jsonl"
    done = {r["conv_id"] for r in read_jsonl(raw_path)}
    todo = [r for r in plan if r["conv_id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{args.axis}: 作成済み {len(done)} / 全 {len(plan)} 会話。今回 {len(todo)} 会話を作ります")

    lock = threading.Lock()
    ok = ng = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex, open(raw_path, "a", encoding="utf-8") as f:
        futs = {ex.submit(call_haiku, client, r): r for r in todo}
        for fut in as_completed(futs):
            row = futs[fut]
            try:
                turns = fut.result()
                with lock:
                    f.write(json.dumps({**row, "model": MODEL, "turns": turns}, ensure_ascii=False) + "\n")
                    f.flush()
                ok += 1
            except Exception as e:
                ng += 1
                print(f"  失敗 {row['conv_id']}: {e}")
                with lock, open(raw_path.parent / "errors.jsonl", "a", encoding="utf-8") as ef:
                    ef.write(json.dumps({"conv_id": row["conv_id"], "error": str(e),
                                         "raw": getattr(e, "raw", "")}, ensure_ascii=False) + "\n")
            if (ok + ng) % 10 == 0:
                print(f"  {ok + ng}/{len(todo)}")
    print(f"完了: 成功 {ok}、失敗 {ng}（失敗した分は、もう一度 gen を実行すると作り直します）")


# ---------------------------------------------------------------- filter
KANJI = re.compile(r"[一-鿿々]")
FIRST_PERSON = re.compile(r"ぼく|ボク|わたし|あたし|おれ|オレ|僕|私|俺")
ANIMAL = re.compile(r"ワン|ニャ|にゃー|にゃん")
INVITE = re.compile(r"食べよ|たべよ|飲もう|のもう|食べに行|たべにい|散歩(しよ|行こ|いこ)|さんぽ(しよ|いこ)|持ってく|もってく|取ってく|とってく")
BODY = re.compile(r"しっぽ|シッポ|尻尾|肉球|にくきゅう|ひげ|ヒゲ|羽根|羽ばた|つばさ|翼|ぴょんぴょん|前足|まえあし|毛並み")


def bigrams(s):
    s = re.sub(r"[\s、。！？!?…ー〜]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def reject_reason(rec):
    reply = rec["reply"]
    owner_last = rec["owner_last"]
    n = len(re.sub(r"\s", "", reply))
    max_len = STAGES[rec["stage"]]["max"] * talk_mult(rec["axis"], rec["stage"])
    if n < 2:
        return "短すぎ"
    if n > max_len:
        return "長すぎ"
    if ANIMAL.search(reply):
        return "鳴き声"
    if BODY.search(reply):
        return "種族・体の言葉"
    if INVITE.search(reply):
        return "できないことに誘う"
    # 「ごはん！」「えっ！」のような短い感嘆は数えず、8文字以上のまとまりだけを1文と数える
    sentences = [s for s in re.split(r"[。！？!?]+", reply) if len(re.sub(r"[\s、]", "", s)) >= 8]
    if rec["stage"] in (2, 3) and len(sentences) > (4 if rec["axis"] == "talkative" else 2):
        return "文が多すぎ"
    if rec["stage"] in (2, 3):
        other_fp = [fp for fp in FIRST_PERSONS if fp != rec.get("first_person", "ぼく")]
        if re.search("|".join(other_fp), reply):
            return "一人称がちがう"
    if rec["time"] == "夜" and re.search(r"夜になったら|夜になると|夜になれば", reply):
        return "夜なのに夜になったら"
    if rec["pet_name"] in reply or "飼い主" in reply:
        return "名前・飼い主と言う"
    a, b = bigrams(reply), bigrams(owner_last)
    if a and b and len(a & b) / len(a | b) > 0.5:
        return "オウム返し"
    if rec["stage"] == 1:
        if KANJI.search(reply):
            return "赤ちゃんなのに漢字"
        if FIRST_PERSON.search(reply):
            return "赤ちゃんなのに一人称"
        hab = AXES[rec["ending_axis"]]
        part = reply[:8] if hab.get("pos") == "start" else reply[-10:]
        if hab["core"] not in part:
            return "赤ちゃんなのに口ぐせなし"
    if rec["stage"] == 2 and n > 12 and not KANJI.search(reply):
        return "子どもなのに漢字なし"
    if rec["stage"] == 3:
        hab = AXES[rec["ending_axis"]]
        part = reply[:8] if hab.get("pos") == "start" else reply[-8:]
        if hab["core"] in part:
            return "育ったなのに口ぐせ"
    return None


def conv_to_records(conv, rng):
    system = build_system_prompt(conv["pet_name"], conv["stage"], conv["ending"], time_label(conv),
                                 OWNERS[conv["owner"]], conv.get("first_person", "ぼく"))
    msgs = [{"role": "user" if t["role"] == "owner" else "assistant", "content": t["text"]} for t in conv["turns"]]
    pet_idx = [i for i, m in enumerate(msgs) if m["role"] == "assistant"]
    chosen = sorted(rng.sample(pet_idx, min(MAX_PER_CONV, len(pet_idx))))
    recs = []
    for j in chosen:
        history = msgs[max(0, j - HISTORY):j]
        if history and history[0]["role"] == "assistant":  # 飼い主の発言から始める
            history = history[1:]
        recs.append({
            "id": f"{conv['conv_id']}_{j}",
            **{k: conv[k] for k in ("conv_id", "axis", "stage", "scene", "time", "owner", "ending", "ending_axis", "pet_name")},
            "first_person": conv.get("first_person", "ぼく"),
            "humanness": STAGES[conv["stage"]]["humanness"],
            "owner_last": msgs[j - 1]["content"],
            "reply": msgs[j]["content"],
            # 学習ではこの messages を使い、最後の assistant だけを学習する
            "messages": [{"role": "system", "content": system}] + history + [msgs[j]],
        })
    return recs


def cmd_filter(args):
    d = axis_dir(args.out, args.axis)
    rng = random.Random(SEED)
    kept, reasons, seen = [], Counter(), set()
    total = 0
    phrase_n = Counter()
    for conv in read_jsonl(d / "raw.jsonl"):
        for rec in conv_to_records(conv, rng):
            total += 1
            why = reject_reason(rec)
            key = re.sub(r"[\s、。！？!?…]", "", rec["reply"])
            if why is None and key in seen:
                why = "ほかと同じ文"
            if why is None:
                for ph, cap in PHRASE_CAPS.items():
                    if ph in rec["reply"] and phrase_n[ph] >= cap:
                        why = f"「{ph}」が多い"
                        break
                else:
                    for ph in PHRASE_CAPS:
                        if ph in rec["reply"]:
                            phrase_n[ph] += 1
            if why:
                reasons[why] += 1
                continue
            seen.add(key)
            kept.append(rec)
    write_jsonl(d / "filtered.jsonl", kept)
    print(f"{args.axis}: 取り出した返事 {total} 件 → 残った {len(kept)} 件")
    for k, v in reasons.most_common():
        print(f"  除いた理由: {k} {v} 件")
    for name, key in (("段階", "stage"), ("場面", "scene"), ("時間", "time"), ("飼い主", "owner")):
        print(f"  {name}: {dict(Counter(r[key] for r in kept))}")
    need = N_TRAIN + N_VAL
    if len(kept) < need:
        print(f"  ※ {need} 件に {need - len(kept)} 件足りません（全会話を作ったあとなら、N_CONV を増やして plan → gen）")


# ---------------------------------------------------------------- show
def cmd_show(args):
    recs = read_jsonl(axis_dir(args.out, args.axis) / "filtered.jsonl")
    for r in random.Random(args.seed).sample(recs, min(args.n, len(recs))):
        print(f"[{STAGES[r['stage']]['label']}・{r['scene']}・{r['time']}・{r['owner']}・口ぐせ{r['ending']}]")
        print(f"  飼い主: {r['owner_last']}")
        print(f"  ペット: {r['reply']}\n")


# ---------------------------------------------------------------- split
def cmd_split(args):
    d = axis_dir(args.out, args.axis)
    recs = read_jsonl(d / "filtered.jsonl")
    by_conv = {}
    for r in recs:
        by_conv.setdefault(r["conv_id"], []).append(r)
    convs = list(by_conv)
    random.Random(SEED).shuffle(convs)
    val, train = [], []
    for c in convs:  # 同じ会話の返事が学習と検証に分かれないよう、会話単位で分ける
        (val if len(val) < N_VAL else train).extend(by_conv[c])
    train = train[:N_TRAIN]
    write_jsonl(d / "train.jsonl", train)
    write_jsonl(d / "val.jsonl", val)
    print(f"{args.axis}: 学習 {len(train)} 件・検証 {len(val)} 件")
    if len(train) < N_TRAIN:
        print(f"  ※ 学習が {N_TRAIN} 件に足りません。6軸で数をそろえるため、足りない軸は会話を足してください")


def main():
    p = argparse.ArgumentParser(description="性格LoRAの教師データを作る")
    p.add_argument("cmd", choices=["plan", "more", "gen", "filter", "show", "split"])
    p.add_argument("--axis", choices=list(AXES))
    p.add_argument("--out", default="data/teacher")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("-n", type=int, default=15)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--add", type=int, default=0, help="more で足す会話の数（省略すると自動）")
    args = p.parse_args()
    if args.cmd != "plan" and not args.axis:
        p.error("--axis を指定してください（例: --axis active）")
    {"plan": cmd_plan, "more": cmd_more, "gen": cmd_gen, "filter": cmd_filter, "show": cmd_show, "split": cmd_split}[args.cmd](args)


if __name__ == "__main__":
    main()