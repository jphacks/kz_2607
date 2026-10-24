"""
eval_route.py — 学習済みの判定モデルを、振り分けの評価用データで比べる（学習はしない）

  python eval_route.py --data route_dev.jsonl --ckpt v2/best.pt v3/best.pt v7/best.pt \
      --cache_dir /content/drive/MyDrive/jphacks/pet_ai/ruri_cache

表示するもの
- 正解率（迷う例は、正解に 0.3 以上付けた選択肢なら当たりとする「許容」も）
- 正解率の幅（ブートストラップで 90% の範囲。データが少ないと幅が広くなる）
- 混同行列と、間違えた文
- 2つ以上のモデルを渡すと、どの文で答えが分かれたか
"""
import argparse
import random

import torch

from kz_2607.ai.judge_code.pet_judge_data import JudgeDataset, RuriEncoder, load_jsonl
from kz_2607.ai.judge_code.pet_judge_model import load_judge


def run_name(path):
    """表示用の名前（…/v9/best.pt → v9、+ でつないだものは v9+v9s1+v9s2）"""
    return "+".join(q.rstrip("/").split("/")[-2] if "/" in q else q for q in path.split("+"))


def gold_top(route):
    return route if isinstance(route, str) else max(route, key=route.get)


def lenient_ok(route, pred):
    return pred == gold_top(route) or (isinstance(route, dict) and route.get(pred, 0) >= 0.3)


def interval(hits, n_boot=2000, seed=0):
    rng = random.Random(seed)
    n = len(hits)
    accs = sorted(sum(hits[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return accs[int(n_boot * 0.05)], accs[int(n_boot * 0.95)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--ckpt", required=True, nargs="+")
    ap.add_argument("--cache_dir", default=None)
    ap.add_argument("--show", type=int, default=15)
    a = ap.parse_args()

    rows = [r for r in load_jsonl(a.data) if (r.get("labels") or {}).get("route") is not None]
    preds, enc = {}, None
    print(f"評価用データ: {a.data}（{len(rows)} 件）\n")
    for path in a.ckpt:
        model, cfg, meta = load_judge(path)
        if enc is None:
            enc = RuriEncoder(meta.get("ruri_model", "cl-nagoya/ruri-v3-130m"), meta.get("prefix", "トピック: "),
                              cache_dir=a.cache_dir)
        ds = JudgeDataset(rows, enc, cfg)
        with torch.no_grad():
            p = model(ds.emb, ds.speaker, ds.pad)["route"].argmax(-1).tolist()
        pred = [cfg.route_labels[i] for i in p]
        preds[path] = pred

        strict = [int(pr == gold_top(r["labels"]["route"])) for r, pr in zip(rows, pred)]
        lenient = [int(lenient_ok(r["labels"]["route"], pr)) for r, pr in zip(rows, pred)]
        lo, hi = interval(strict)
        name = run_name(path)
        print(f"==== {name}")
        print(f"  正解率 {sum(strict) / len(rows):.1%}（90%の範囲 {lo:.1%}〜{hi:.1%}）  "
              f"迷う例を許容 {sum(lenient) / len(rows):.1%}")
        labels = cfg.route_labels
        print("  混同行列（行=正解, 列=予測）")
        print("  " + " " * 14 + "".join(f"{l[:4]:>8s}" for l in labels))
        for gl in labels:
            cnt = [sum(1 for r, pr in zip(rows, pred) if gold_top(r["labels"]["route"]) == gl and pr == c) for c in labels]
            print(f"  {gl:<{14 - len(gl)}s}" + "".join(f"{v:8d}" for v in cnt))
        miss = [(r, pr) for r, pr, ok in zip(rows, pred, lenient) if not ok]
        if miss:
            print(f"  間違えた例（迷う例の許容でも外れたもの {len(miss)} 件中 {min(len(miss), a.show)} 件）")
            for r, pr in miss[:a.show]:
                ctx = " / ".join(t["text"] for t in r["turns"][:-1])
                print(f"    「{r['turns'][-1]['text']}」 正解={r['labels']['route']} 予測={pr}" + (f"  （前: {ctx}）" if ctx else ""))
        print()

    if len(preds) >= 2:
        names = list(preds)
        diff = [i for i in range(len(rows)) if len({preds[n][i] for n in names}) > 1]
        print(f"==== モデルで答えが分かれた文: {len(diff)} 件")
        for i in diff[:a.show]:
            r = rows[i]
            outs = "  ".join(f"{run_name(n)}={preds[n][i]}" for n in names)
            print(f"  「{r['turns'][-1]['text']}」 正解={r['labels']['route']}  {outs}")


if __name__ == "__main__":
    main()