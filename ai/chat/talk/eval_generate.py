"""
評価用の返事を作る（Mac・llama-server、API は使わない）

使い方（chat/talk で、mix_mac_server.sh を起動したまま）:
    python eval_generate.py                         # 性格LoRA あり（上位3軸・s=1.5）と、なし（元のモデル）
    python eval_generate.py --scale 1.0 --tag s10   # 別の強さも試すとき
    python3 eval_generate.py --temp 0.4 --min-p 0.1 --tag t04 --no-base            # 言葉の選び方を厳しく
    python3 eval_generate.py --temp 0.4 --min-p 0.1 --baby-via-child --tag t04b --no-base  # 赤ちゃんは子どもで作ってから直す
    python3 eval_generate.py --reconvert           # baby_talk.py を直したとき：保存してある元の返事から赤ちゃん言葉を作り直す
    python3 eval_generate.py --no-lora --temp 0.4 --min-p 0.1 --baby-via-child --tag ljp4_base   # 別のモデルを LoRA なしで
（--baby-via-child には pykakasi が要る：uv pip install pykakasi）
入力: eval_set.jsonl（Colab の eval_make_set.py で作ったもの。このフォルダに置く）
出力: eval_replies.jsonl（Colab にアップロードして eval_judge.py で採点する）
"""
import argparse
import json
import re
import time
from pathlib import Path

import requests

from kz_2607.ai.chat.talk.teacher_data import build_system_prompt

URL = "http://127.0.0.1:8081"
HERE = Path(__file__).parent
AXIS_ORDER = ["active", "affection", "talkative", "logic", "curious", "night"]


def lora_ids():
    js = requests.get(f"{URL}/lora-adapters", timeout=10).json()
    ids = {}
    for a in js:
        m = re.search(r"axis_(\w+)\.gguf", a["path"])
        if m and m.group(1) in AXIS_ORDER:
            ids[m.group(1)] = a["id"]
    missing = [a for a in AXIS_ORDER if a not in ids]
    if missing:
        raise SystemExit(f"サーバーに載っていない LoRA があります: {missing}")
    return ids


def scales(v, s, k):
    order = sorted(AXIS_ORDER, key=lambda a: (-v[a], AXIS_ORDER.index(a)))[:k]
    total = sum(v[a] for a in order)
    return {a: (s * v[a] / total if a in order else 0.0) for a in AXIS_ORDER}


HARMONY_CUT = re.compile(r"<\|(end|return|start|call)\|>")


def clean(text):
    """LLM-jp-4 など Harmony 形式のモデルの印（<|channel|>final<|message|> など）を取り除いて、返事だけにする"""
    if "<|message|>" in text:
        text = text.split("<|message|>")[-1]
    text = HARMONY_CUT.split(text)[0]
    return text.strip()


def gen(ids, it, sc, seed, args, stage=None):
    stage = stage or it["stage"]
    system = build_system_prompt(it["pet_name"], stage, it["ending"], it["time_label"], it["owner"], it["first_person"])
    body = {
        "messages": [{"role": "system", "content": system}] + it["context"],
        "max_tokens": 100, "temperature": args.temp, "top_p": args.top_p, "min_p": args.min_p,
        "repeat_penalty": 1.1, "seed": seed,
    }
    if ids:
        body["lora"] = [{"id": ids[a], "scale": round(sc.get(a, 0.0), 3)} for a in AXIS_ORDER]
    r = requests.post(f"{URL}/v1/chat/completions", json=body, timeout=120)
    r.raise_for_status()
    return clean(r.json()["choices"][0]["message"]["content"] or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(HERE / "eval_set.jsonl"))
    ap.add_argument("--out", default=str(HERE / "eval_replies.jsonl"))
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--tag", default="lora", help="この設定の名前（採点の表に出る）")
    ap.add_argument("--no-base", action="store_true", help="元のモデル（LoRA なし）は作らない")
    ap.add_argument("--temp", type=float, default=0.7, help="温度（低いほど無難な言葉を選ぶ）")
    ap.add_argument("--top-p", type=float, default=0.9)
    ap.add_argument("--min-p", type=float, default=0.0, help="いちばん確率の高い言葉の◯倍未満の言葉は選ばない（0.1 など）")
    ap.add_argument("--baby-via-child", action="store_true", help="赤ちゃんは子どもの段階で作ってから、ひらがな・口ぐせに直す")
    ap.add_argument("--no-lora", action="store_true", help="LoRA を使わない（LoRA を載せていないサーバー・別のモデル用）")
    ap.add_argument("--reconvert", action="store_true", help="返事は作らず、赤ちゃん言葉への直しだけやり直す")
    args = ap.parse_args()

    if args.reconvert:
        from kz_2607.ai.chat.talk.baby_talk import to_baby
        endings = {json.loads(l)["id"]: json.loads(l)["ending"] for l in open(args.set, encoding="utf-8") if l.strip()}
        rows = [json.loads(l) for l in open(args.out, encoding="utf-8") if l.strip()]
        n = 0
        for r in rows:
            if r.get("raw"):
                new = to_baby(r["raw"], endings[r["id"]])
                n += new != r["reply"]
                r["reply"] = new
        with open(args.out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"赤ちゃん言葉を作り直しました（変わった返事 {n} 件）。採点は eval_judge.py --rejudge-stage 1 で")
        return

    items = [json.loads(l) for l in open(args.set, encoding="utf-8") if l.strip()]
    ids = {} if args.no_lora else lora_ids()
    out = Path(args.out)
    done = set()
    if out.exists():
        done = {(json.loads(l)["id"], json.loads(l)["system"]) for l in open(out, encoding="utf-8") if l.strip()}
    if args.no_lora:
        systems = [(args.tag, 0.0, 0)]
    else:
        systems = [(args.tag, args.scale, args.topk)] + ([] if args.no_base else [("base", 0.0, 0)])
    t0 = time.time()
    n = 0
    with open(out, "a", encoding="utf-8") as f:
        for it in items:
            for tag, s, k in systems:
                if (it["id"], tag) in done:
                    continue
                sc = scales(it["v"], s, k) if s > 0 else {}
                seed = int(it["id"][1:])
                rec = {"id": it["id"], "system": tag, "scales": {a: round(x, 2) for a, x in sc.items() if x > 0}}
                if args.baby_via_child and it["stage"] == 1:
                    from kz_2607.ai.chat.talk.baby_talk import to_baby
                    raw = gen(ids, it, sc, seed, args, stage=2)
                    rec.update(raw=raw, reply=to_baby(raw, it["ending"]))
                else:
                    rec["reply"] = gen(ids, it, sc, seed, args)
                rec["settings"] = {"temp": args.temp, "top_p": args.top_p, "min_p": args.min_p,
                                   "baby_via_child": args.baby_via_child}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
            if n and n % 20 == 0:
                print(f"  {n} 件", flush=True)
    print(f"保存しました: {out}（今回 {n} 件、{(time.time() - t0) / 60:.1f} 分）")


if __name__ == "__main__":
    main()