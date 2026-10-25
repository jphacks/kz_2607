"""
tools/live_check.py — 起動中の AIサーバー（本物の判定モデル＋8081 の性格LoRA）に /talk を送って、
                      「振り分け先」「選んだもの」「返事」を表にする

モデルは偽物にしない。バックエンドの代わりをするのはここだけ：
  ・recentTurns（直近5往復、seq は飼い主 2s−1・ペット 2s）と summarizedSeq（要約済みの往復 ×2）を作って送る
  ・要約は OpenAI を呼ばず、要約プロンプト（backend/functions/petlogic/memory.py の SYSTEM_A）の書き方の決まった文を使う
  ・交換のあとは、前の代の思い出（pastMemories・ぼかし済み）と旅の記録（journeys）を送る
雑談の回（1〜5回目など）は本当に /talk に送り、ペットの返事をそのまま recentTurns に入れる。
「覚えてる？」の確かめ（下の PROBES）は会話に入れない（同じ状態で何通りも聞くため）。

使い方（先に 8081 と AIサーバーを起動しておく）:
    cd kz_2607/ai/server
    ../chat/.venv/bin/python tools/live_check.py                          # http://127.0.0.1:8000 に送る
    ../chat/.venv/bin/python tools/live_check.py --only name,exchange     # シナリオをしぼる（name・baby・exchange）
    ../chat/.venv/bin/python tools/live_check.py -o live.md --jsonl live.jsonl   # 表と全部の応答を書き出す
    ../chat/.venv/bin/python tools/live_check.py --url https://xxxx.trycloudflare.com
合い言葉（X-Api-Key）は環境変数 TALK_API_KEY、無ければ ai/server/.env から読む。

起動（それぞれ別のターミナルで）:
    # 1. 性格LoRA（8081）。ai/chat/talk/lora/axis_<軸>/ に6軸の LoRA を置いておく
    cd kz_2607/ai/chat/talk && source ../.venv/bin/activate && bash mix_mac_server.sh
    # 2. LoRA なし（8080）。無くても起動はできる（ほかが使えないときの返事・覚える言葉に使う。この確認は want_learn=false）
    llama-server -hf LiquidAI/LFM2.5-1.2B-JP-GGUF --host 127.0.0.1 --port 8080 -c 4096
    # 3. AIサーバー（8000）。判定モデル（ai/judge/v9*/best.pt）と Ruri はこの中で読み込む
    cd kz_2607/ai/server && source ../chat/.venv/bin/activate && uvicorn talk_server:app --host 0.0.0.0 --port 8000
    #    DEBUG_PROMPT=1 を付けると、8081 に送るプロンプト全文と思い出の選び方がログに出る
    curl http://127.0.0.1:8000/health      # ok・chat_lora.lora・memory.embedder を見る

表の「期待」は返事に入っていてほしい言葉（「!」で始まるものは入っていてほしくない言葉）。目で確かめるときの目安。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SERVER_DIR = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
AXES = {"talkative": 0.6, "affection": 0.4, "active": 0.2}
NAME_MAP = {"{person_1}": "ゆうと"}
CHAT_TURNS = ["今日は公園で散歩したよ", "いちごのアイスが好きなんだ", "学校で数学のテストがあった",
              "夜ごはんはカレーだった", "週末は映画を見に行きたいな", "最近ギターの練習をしてる",
              "友だちとゲームをした", "雨がふってきたね", "明日は早起きしなきゃ"]

# 「覚えてる？」の確かめ。(発言, 期待)
NAME_PROBES = [("ぼくの名前、覚えてる？", ["ゆうと"]), ("名前覚えてる？", ["ゆうと"]), ("俺の名前わかる？", ["ゆうと"]),
               ("ぼくの好きなもの、覚えてる？", ["いちご"]), ("きみの名前、覚えてる？", ["モチ", "!ゆうと"])]
EXCHANGE_PROBES = ["昨日なにしたっけ？", "この前なにしたっけ？", "今日なにしたっけ？", "前の飼い主さんとは何の話をした？",
                   "昨日なにしてたっけ", "この前なにしてたっけ？", "前の飼い主さんと何話してた？", "今日何したか覚えてる？"]


def api_key() -> str:
    if os.environ.get("TALK_API_KEY"):
        return os.environ["TALK_API_KEY"]
    env = SERVER_DIR / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("TALK_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def noon_today() -> str:
    return datetime.now(JST).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()


class Client:
    def __init__(self, url, key):
        self.url, self.headers = url.rstrip("/"), ({"X-Api-Key": key} if key else {})
        self.rows = []

    def reset(self, pet_id):
        requests.post(f"{self.url}/reset", params={"petId": pet_id}, headers=self.headers, timeout=30).raise_for_status()

    def talk(self, body):
        t0 = time.perf_counter()
        r = requests.post(f"{self.url}/talk", json={"want_learn": False, "petName": "モチ", "personalityAxes": AXES,
                                                     "firstPerson": "ぼく", **body},
                          headers=self.headers, timeout=180)
        r.raise_for_status()
        js = r.json()
        js["_ms"] = round((time.perf_counter() - t0) * 1000)
        return js

    def probe(self, scenario, body, expect=None):
        js = self.talk(body)
        self.rows.append({"scenario": scenario, "text": body["text"], "expect": expect or [], "res": js})
        print(f"[{scenario}] {body['text']} → {js['reply_text']}", flush=True)
        return js


class Pet:
    """バックエンドの代わり：その代の会話（往復の番号付き）を持ち、直近5往復を recentTurns にする。"""

    def __init__(self, client, pet_id, generation=1):
        self.c, self.pet_id, self.generation, self.turns = client, pet_id, generation, []
        client.reset(pet_id)

    def recent(self):
        out = []
        for s, (text, reply) in list(enumerate(self.turns, 1))[-5:]:
            out += [{"speaker": "owner", "text": text, "seq": 2 * s - 1}, {"speaker": "pet", "text": reply, "seq": 2 * s}]
        return out

    def body(self, text, summarized_rounds=None, **extra):
        b = {"petId": self.pet_id, "text": text, "generation": self.generation, "recentTurns": self.recent(), **extra}
        if summarized_rounds:
            b["summarizedSeq"] = 2 * summarized_rounds
        return b

    def say(self, text, **extra):
        """会話に入れる回（雑談など）。返事を recentTurns に残す。"""
        js = self.c.talk(self.body(text, **extra))
        self.turns.append((text, js["reply_text"]))
        return js


def scenario_name(c, stage_name, humanness=None):
    """1回目に名前を教える → 6回目（要約はまだ届いていない）・11回目（1〜5回目の要約と facts が届いた）に聞く。"""
    extra = {"humanness": humanness, "stage": stage_name} if humanness is not None else {}
    pet = Pet(c, f"live-{stage_name}-{int(time.time())}")
    pet.say("ぼくの名前はゆうとだよ", **extra)
    for t in CHAT_TURNS[:4]:
        pet.say(t, **extra)
    for text, exp in NAME_PROBES:                                   # 6回目：recentTurns に1〜5回目
        c.probe(f"{stage_name}・6回目", pet.body(text, **extra), exp)
    pet.say(NAME_PROBES[0][0], **extra)                             # 6回目として会話にも入れる
    for t in CHAT_TURNS[4:8]:
        pet.say(t, summarized_rounds=5, **extra)
    summary = {"memories": [{"id": "m1", "text": "名前は{person_1}だと話してくれた", "createdAt": noon_today()},
                            {"id": "m2", "text": "いちごのアイスが好きだと話してくれた", "createdAt": noon_today()}],
               "nameMap": NAME_MAP, "facts": {"ownerName": "{person_1}", "likes": ["いちごのアイス"]}}
    for text, exp in NAME_PROBES:                                   # 11回目：recentTurns に6〜10回目
        c.probe(f"{stage_name}・11回目", pet.body(text, summarized_rounds=5, **extra, **summary), exp)


def scenario_exchange(c):
    """交換直後（2代目の1回目）。memories 空・recentTurns 空・pastMemories に前の代の思い出。"""
    for label, text, word in [("Aのペット", "冷やし中華を食べたと話してくれた", "冷やし中華"),
                              ("Bのペット", "あのお祭りで花火を見たと言っていた", "花火")]:
        pet_id = f"live-exchange-{label}-{int(time.time())}"
        c.reset(pet_id)
        past = [{"id": "p1", "text": text, "generation": 1, "createdAt": noon_today()}]
        journeys = [{"generation": 1, "summary": "夏の話をよくした", "timeOfDay": "夜", "talkCount": 6}]
        for q in EXCHANGE_PROBES:
            c.probe(f"交換直後・{label}", {"petId": pet_id, "text": q, "generation": 2, "recentTurns": [],
                                         "pastMemories": past, "journeys": journeys, "nameMap": NAME_MAP,
                                         "facts": {"ownerName": "{person_1}"}}, [word, "!ゆうと", "!昨日"])


def picked_of(res) -> str:
    m = res.get("memory") or {}
    if m:
        parts = [f"{m.get('kind')}" + (f"→{m['answer_kind']}" if m.get("answer_kind") else "")]
        if m.get("fact_picked"):
            parts.append(f"facts {m['fact_picked']}")
        if m.get("picked"):
            parts.append(f"{m['picked']}")
        if m.get("keys"):
            parts.append(f"先頭 {m['keys'][0]}")
        parts.append(f"{m.get('check')}")
        return " ".join(parts)
    s = res.get("pet_self") or {}
    return f"ペット自身 {s.get('kind')} {s.get('fact_check')}" if s else ""


def verdict(expect, reply) -> str:
    if not expect:
        return ""
    ok = all((w[1:] not in reply) if w.startswith("!") else (w in reply) for w in expect)
    return "○" if ok else "×"


def table(rows) -> str:
    def cell(x):
        return str(x).replace("|", "／").replace("\n", " ")
    out = ["| # | シナリオ | 発言 | 振り分け先 | 選んだもの | 返事 | 期待 | |", "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        res = r["res"]
        route = res["route"] + (f"（{res['judge']['override']}）" if res["judge"].get("override") else "")
        out.append("| " + " | ".join(cell(x) for x in [i, r["scenario"], r["text"], f"{route} / {res['generator']}",
                                                        picked_of(res), res["reply_text"], "・".join(r["expect"]),
                                                        verdict(r["expect"], res["reply_text"])]) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("TALK_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--only", default="name,baby,exchange")
    ap.add_argument("-o", "--out", help="表（Markdown）の書き出し先")
    ap.add_argument("--jsonl", help="全部の応答の書き出し先")
    args = ap.parse_args()
    c = Client(args.url, api_key())
    try:
        health = requests.get(f"{c.url}/health", timeout=10).json()
    except Exception as e:
        sys.exit(f"AIサーバーにつながりません（{c.url}）: {e}")
    print(f"[health] {json.dumps(health, ensure_ascii=False)}")
    if not health.get("ok") or not health.get("chat_lora", {}).get("lora"):
        print("※ 判定モデルか 8081 の性格LoRA が読めていません。結果は本物のモデルになりません", file=sys.stderr)
    only = set(args.only.split(","))
    if "name" in only:
        scenario_name(c, "育った")
    if "baby" in only:
        scenario_name(c, "赤ちゃん", humanness=0.0)
    if "exchange" in only:
        scenario_exchange(c)
    md = table(c.rows)
    print("\n" + md)
    if args.out:
        Path(args.out).write_text(md + "\n", encoding="utf-8")
        print(f"→ {args.out}")
    if args.jsonl:
        with open(args.jsonl, "w", encoding="utf-8") as f:
            for r in c.rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        print(f"→ {args.jsonl}")


if __name__ == "__main__":
    main()
