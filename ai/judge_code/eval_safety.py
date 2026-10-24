"""
eval_safety.py — 安全ヘッドを safety_eval.jsonl で測り、しきい値を決める

  python eval_safety.py --ckpt /content/drive/MyDrive/jphacks/pet_ai/judge/v3/best.pt \
      --cache_dir /content/drive/MyDrive/jphacks/pet_ai/ruri_cache

1. dev（調整用）で、しきい値ごとの「見逃さなさ（再現率）」と「正しさ（適合率）」を表にする
2. 見逃しを重く見る F2 がいちばん高いしきい値を選ぶ（安全は見逃しのほうが困るため）
3. そのしきい値で test（最後に1回だけ測る用）を測り、見逃した文・間違って止めた文を表示する

「危険らしさ」は、3つの種類（暴言・差別・性的）の確率のうち一番大きいもの。
"""
import argparse
import json

import torch

from pet_judge_data import JudgeDataset, RuriEncoder, load_jsonl
from pet_judge_model import load_judge


def unsafe_prob(model, ds):
    with torch.no_grad():
        out = model(ds.emb, ds.speaker, ds.pad)
    if "unsafe" in out:                                   # 「危険かどうか」の専用ヘッドがある版
        return torch.sigmoid(out["unsafe"]).squeeze(-1)
    return torch.sigmoid(out["safety"]).max(-1).values


def scores(p, y, th):
    pred = p >= th
    tp = int((pred & y).sum()); fp = int((pred & ~y).sum()); fn = int((~pred & y).sum())
    rec = tp / (tp + fn) if tp + fn else 0.0
    prec = tp / (tp + fp) if tp + fp else 0.0
    f2 = 5 * prec * rec / (4 * prec + rec) if prec + rec else 0.0
    return rec, prec, f2, fp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True, nargs="+", help="比べたい best.pt（複数可）")
    ap.add_argument("--data", default="safety_eval.jsonl")
    ap.add_argument("--cache_dir", default=None)
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--ng", action="store_true", help="ng_words.py の言い回しに当たった文は、危険らしさを 1.0 にする（モデル＋一覧）")
    a = ap.parse_args()

    rows = load_jsonl(a.data)
    enc = None
    for path in a.ckpt:
        model, cfg, meta = load_judge(path)
        if enc is None:
            enc = RuriEncoder(meta.get("ruri_model", "cl-nagoya/ruri-v3-130m"), meta.get("prefix", "トピック: "),
                              cache_dir=a.cache_dir)
        res = {}
        for split in ("dev", "test"):
            part = [r for r in rows if r["split"] == split]
            ds = JudgeDataset(part, enc, cfg)
            p = unsafe_prob(model, ds)
            if a.ng:
                from ng_words import check
                p = torch.tensor([1.0 if check(r["turns"][-1]["text"]) else float(v) for r, v in zip(part, p)])
            res[split] = (part, p, torch.tensor([bool(r["labels"]["safety"]) for r in part]))

        print(f"\n==================== {path}" + ("  ＋ NGワードの一覧" if a.ng else ""))
        part, p, y = res["dev"]
        print(f"[dev] 危険 {int(y.sum())} / 安全 {int((~y).sum())}")
        print("  しきい値  見逃さなさ  正しさ   F2   間違って止めた数")
        best = (0.5, -1)
        for th in (0.5, 0.4, 0.3, 0.2, 0.15, 0.1, 0.05, 0.02):
            rec, prec, f2, fp = scores(p, y, th)
            print(f"   {th:4.2f}     {rec:5.2f}     {prec:5.2f}  {f2:5.2f}   {fp}")
            if f2 > best[1]:
                best = (th, f2)
        th = best[0]
        print(f"  → しきい値 {th} を選びます（F2 が最大）")

        part, p, y = res["test"]
        rec, prec, f2, fp = scores(p, y, th)
        print(f"[test] しきい値 {th}: 見逃さなさ {rec:.2f}  正しさ {prec:.2f}  F2 {f2:.2f}  （参考: 0.5 のとき "
              f"見逃さなさ {scores(p, y, 0.5)[0]:.2f}）")
        for cat in ("暴言", "差別", "性的"):
            idx = [i for i, r in enumerate(part) if cat in r["labels"]["safety"]]
            if idx:
                hit = sum(bool(p[i] >= th) for i in idx)
                print(f"   {cat}: {hit}/{len(idx)}")
        miss = [(r, float(p[i])) for i, r in enumerate(part) if y[i] and p[i] < th]
        fa = [(r, float(p[i])) for i, r in enumerate(part) if not y[i] and p[i] >= th]
        if miss:
            print("  見逃した文:")
            for r, v in sorted(miss, key=lambda x: x[1])[:a.show]:
                print(f"    {v:.2f}  {r['turns'][-1]['text']}  {r['labels']['safety']}")
        if fa:
            print("  間違って止めた文:")
            for r, v in sorted(fa, key=lambda x: -x[1])[:a.show]:
                print(f"    {v:.2f}  {r['turns'][-1]['text']}")


if __name__ == "__main__":
    main()