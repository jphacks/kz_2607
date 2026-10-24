"""
DPO ② 今の LoRA に返事を作らせる（Mac・llama-server、API は使わない）

使い方（chat/talk で、mix_mac_server.sh を起動したまま。prompts.jsonl をこのフォルダに置く）:
    python3 dpo_sample.py
出力: dpo_samples.jsonl（Colab の chat/dpo/ に置いて dpo_judge.py で採点する）

- 会話ごとに、その軸の LoRA だけ（強さ 1.0＝学習したときと同じ）で返事を2つ作る
- DPO は「今の LoRA がつい言ってしまう外れた返事」を下げる学習なので、
  本番より少し温度を上げて（0.7）、外れ方をいろいろ集める
- 途中で止めても、もう一度実行すれば続きから作る
"""
import argparse
import json
import time
from pathlib import Path

import requests

from eval_generate import URL, lora_ids, AXIS_ORDER

HERE = Path(__file__).parent


def gen(ids, prompt, axis, seed, temp):
    body = {
        "messages": prompt, "max_tokens": 100, "temperature": temp, "top_p": 0.9, "min_p": 0.05,
        "repeat_penalty": 1.1, "seed": seed,
        "lora": [{"id": ids[a], "scale": 1.0 if a == axis else 0.0} for a in AXIS_ORDER],
    }
    r = requests.post(f"{URL}/v1/chat/completions", json=body, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default=str(HERE / "prompts.jsonl"))
    ap.add_argument("--out", default=str(HERE / "dpo_samples.jsonl"))
    ap.add_argument("--n", type=int, default=2, help="会話1つあたりの返事の数")
    ap.add_argument("--temp", type=float, default=0.7)
    args = ap.parse_args()

    prompts = [json.loads(l) for l in open(args.prompts, encoding="utf-8") if l.strip()]
    ids = lora_ids()
    out = Path(args.out)
    done = set()
    if out.exists():
        done = {json.loads(l)["id"] for l in open(out, encoding="utf-8") if l.strip()}
    t0, n = time.time(), 0
    with open(out, "a", encoding="utf-8") as f:
        for k, p in enumerate(prompts):
            if p["id"] in done:
                continue
            samples = [gen(ids, p["prompt"], p["axis"], seed=k * 10 + j, temp=args.temp) for j in range(args.n)]
            f.write(json.dumps({"id": p["id"], "samples": samples}, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            if n % 50 == 0:
                print(f"  {n} 個（{(time.time() - t0) / 60:.1f} 分）", flush=True)
    print(f"保存しました: {out}（今回 {n} 個、{(time.time() - t0) / 60:.1f} 分）")


if __name__ == "__main__":
    main()