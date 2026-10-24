"""
6軸の性格LoRAを、本番と同じように割合で混ぜて返事を比べる（Mac・llama-server）

使い方（mix_mac_server.sh でサーバーを起動したまま、別のターミナルで。teacher_data.py を同じフォルダに置く）:
    python mix_check.py                 # すべて
    python mix_check.py --part single   # 1軸だけ・弱い強さの効き方
    python mix_check.py --part mix      # 混ぜたときの比べ

見ること:
    1. single … 本番の強さ（0.2〜0.4）で、その軸の性格がどれくらい出るか
    2. mix    … 合計の強さ s（1.0・1.5・2.0）と、6軸すべて／上位3軸だけで、
                 「上位の性格がわかるか」「口調が崩れないか」「決まり文句が多くないか」
結果は mix_results.md に保存する（そのまま貼ってもらえれば読みます）。
"""
import argparse
import json
import re
import time
from pathlib import Path

import requests

from kz_2607.ai.chat.talk.teacher_data import AXES, build_system_prompt, hour_to_label

URL = "http://127.0.0.1:8081"
OUT = Path(__file__).parent / "mix_results.md"
LABEL = {k: a["label"] for k, a in AXES.items()}

# 試す発言（飼い主の話し方・時刻つき）
PROBES = [
    ("ただいま、テストよかった！", "標準語のタメ口。口ぐせ「なんか」「けっこう」", 22),
    ("財布落としてもうた…めっちゃへこむわ", "関西弁のタメ口。口ぐせ「めっちゃ」「〜やん」「ほんま」", 21),
    ("おはようございます。今日は雨ですね。", "ていねいな敬語まじり。口ぐせ「〜ですね」「ちょっと」", 7),
    ("今日のお昼、新しいカレー屋さん行ってみた", "若者言葉。口ぐせ「マジで」「それな」「やば」", 13),
]

# 性格の例（v_i。本番ではバックエンドが計算する値）
PROFILES = {
    "元気で知りたがり": {"active": 4, "curious": 3, "affection": 2, "talkative": 1, "logic": 1, "night": 1},
    "甘えんぼの夜型":   {"affection": 4, "night": 3, "talkative": 2, "active": 1, "logic": 1, "curious": 1},
    "理屈っぽいおしゃべり": {"logic": 4, "talkative": 3, "curious": 2, "active": 1, "affection": 1, "night": 1},
    "ほぼ均等":         {"active": 2, "affection": 2, "talkative": 2, "logic": 2, "curious": 2, "night": 2},
}

# 決まり文句（多すぎないかを数える）
TEMPLATES = ["好き", "すき", "声", "そういえば", "どんな", "夜になったら", "つまり", "だよっ"]


def lora_ids():
    js = requests.get(f"{URL}/lora-adapters", timeout=10).json()
    ids = {}
    for a in js:
        m = re.search(r"axis_(\w+)\.gguf", a["path"])
        if m:
            ids[m.group(1)] = a["id"]
    missing = [ax for ax in AXES if ax not in ids]  # common は無くてもよい
    if missing:
        raise SystemExit(f"サーバーに載っていない LoRA があります: {missing}")
    return ids


def scales_from_profile(v, s, top_k=None):
    """p_i = v_i / Σv_j。top_k を指定したら上位 k 軸だけに s を配る"""
    items = sorted(v.items(), key=lambda x: -x[1])
    if top_k:
        items = items[:top_k]
    total = sum(x for _, x in items)
    return {ax: s * x / total for ax, x in items}


def ask(ids, scales, text, owner, hour, stage=3, seed=0, common=0.0):
    system = build_system_prompt("モチ", stage, "〜なの", hour_to_label(hour), owner, "ぼく")
    body = {
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
        "max_tokens": 80, "temperature": 0.7, "top_p": 0.9, "repeat_penalty": 1.1, "seed": seed,
        "lora": [{"id": ids[ax], "scale": round(scales.get(ax, 0.0), 3)} for ax in AXES]
                + ([{"id": ids["common"], "scale": common}] if "common" in ids else []),
    }
    t0 = time.time()
    r = requests.post(f"{URL}/v1/chat/completions", json=body, timeout=120)
    r.raise_for_status()
    js = r.json()
    return js["choices"][0]["message"]["content"].strip(), time.time() - t0


def fmt_scales(sc):
    return "・".join(f"{LABEL[a]} {x:.2f}" for a, x in sorted(sc.items(), key=lambda x: -x[1]) if x > 0)


def part_single(ids, lines):
    lines.append("## 1. 1軸だけ・強さを変えたとき\n")
    lines.append("本番では1軸あたり 0.2〜0.4 くらい。0.2 でも性格が少し出るかを見る。\n")
    for ax in AXES:
        lines.append(f"### {LABEL[ax]}\n")
        for s in (0.0, 0.2, 0.4, 1.0):
            for text, owner, hour in PROBES[:2]:
                reply, _ = ask(ids, {ax: s}, text, owner, hour)
                lines.append(f"- 強さ {s:.1f}｜{text} → {reply}")
        lines.append("")
        print(f"  single: {LABEL[ax]} 完了", flush=True)


def part_mix(ids, lines):
    lines.append("## 2. 混ぜたとき（育った段階）\n")
    counts = {}
    for name, v in PROFILES.items():
        lines.append(f"### {name}（上位：{'・'.join(LABEL[a] for a, _ in sorted(v.items(), key=lambda x: -x[1])[:2])}）\n")
        for mode, top_k in (("6軸すべて", None), ("上位3軸だけ", 3)):
            for s in (1.0, 1.5, 2.0):
                sc = scales_from_profile(v, s, top_k)
                lines.append(f"**{mode}・s={s}**（{fmt_scales(sc)}）")
                key = (mode, s)
                for text, owner, hour in PROBES:
                    reply, sec = ask(ids, sc, text, owner, hour)
                    lines.append(f"- {text}（{hour}時） → {reply}")
                    c = counts.setdefault(key, {"n": 0, "chars": 0, **{t: 0 for t in TEMPLATES}})
                    c["n"] += 1
                    c["chars"] += len(reply)
                    for t in TEMPLATES:
                        c[t] += t in reply
                lines.append("")
        print(f"  mix: {name} 完了", flush=True)

    lines.append("## 3. まとめ（決まり文句が入った返事の数・平均の長さ）\n")
    lines.append("| 混ぜ方 | 件数 | 平均の長さ | " + " | ".join(TEMPLATES) + " |")
    lines.append("|" + "---|" * (3 + len(TEMPLATES)))
    for (mode, s), c in counts.items():
        lines.append(f"| {mode}・s={s} | {c['n']} | {c['chars'] / c['n']:.0f} | "
                     + " | ".join(str(c[t]) for t in TEMPLATES) + " |")


def part_common(ids, lines):
    if "common" not in ids:
        raise SystemExit("共通LoRA（axis_common）がサーバーに載っていません。lora/axis_common を置いて起動し直してください")
    lines.append("## 共通LoRA あり／なし（上位3軸）\n")
    counts = {}
    for name, v in PROFILES.items():
        lines.append(f"### {name}\n")
        for s in (1.0, 1.5):
            sc = scales_from_profile(v, s, 3)
            for common in (0.0, 1.0):
                tag = f"共通{'あり' if common else 'なし'}・s={s}"
                lines.append(f"**{tag}**（{fmt_scales(sc)}）")
                for text, owner, hour in PROBES:
                    reply, _ = ask(ids, sc, text, owner, hour, common=common)
                    lines.append(f"- {text}（{hour}時） → {reply}")
                    c = counts.setdefault(tag, {"n": 0, "chars": 0, **{t: 0 for t in TEMPLATES}})
                    c["n"] += 1
                    c["chars"] += len(reply)
                    for t in TEMPLATES:
                        c[t] += t in reply
                lines.append("")
        print(f"  common: {name} 完了", flush=True)
    lines.append("## まとめ\n")
    lines.append("| 混ぜ方 | 件数 | 平均の長さ | " + " | ".join(TEMPLATES) + " |")
    lines.append("|" + "---|" * (3 + len(TEMPLATES)))
    for tag, c in counts.items():
        lines.append(f"| {tag} | {c['n']} | {c['chars'] / c['n']:.0f} | " + " | ".join(str(c[t]) for t in TEMPLATES) + " |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["all", "single", "mix", "common"], default="all")
    args = ap.parse_args()

    ids = lora_ids()
    print("LoRA の id:", ids)
    lines = ["# 性格LoRAを混ぜたときの返事\n", "口ぐせは全部「〜なの」、一人称は「ぼく」にそろえている。\n"]
    t0 = time.time()
    if args.part in ("all", "single"):
        part_single(ids, lines)
    if args.part in ("all", "mix"):
        part_mix(ids, lines)
    out = OUT
    if args.part == "common":
        part_common(ids, lines)
        out = OUT.with_name("mix_common_results.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"保存しました: {out}（{(time.time() - t0) / 60:.1f} 分）")


if __name__ == "__main__":
    main()