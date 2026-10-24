"""
train_judge.py — 手順3-3：判定モデルの学習・評価・保存

Colab の例:
  !python train_judge.py --train sample_data.jsonl --val_ratio 0.25 \
      --out_dir /content/drive/MyDrive/pet_ai/judge/sample \
      --cache_dir /content/drive/MyDrive/pet_ai/ruri_cache

出力（out_dir）:
  best.pt        検証の損失がいちばん低かったときの重み（load_judge で読める）
  history.json   エポックごとの損失と評価
  split.json     学習・検証に使った会話のID（あとで同じ分け方を再現するため）
"""
import argparse
import json
import random
import time
from dataclasses import asdict
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from pet_judge_data import JudgeDataset, RuriEncoder, label_summary, load_jsonl
from pet_judge_model import JudgeConfig, PetJudge, decide, judge_loss, load_judge

MULTI_HEADS = ("nature", "reaction", "safety")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--train", required=True, help="学習データ（JSONL）")
    p.add_argument("--val", help="検証データ（JSONL）。無ければ --train から分ける")
    p.add_argument("--val_ratio", type=float, default=0.1)
    p.add_argument("--test", help="最後に1回だけ測る評価用データ（自分で付けた gold.jsonl）。学習の判断には使わない")
    p.add_argument("--out_dir", default="runs/judge")
    p.add_argument("--cache_dir", default=None, help="Ruriのベクトルの保存先（Driveにすると再計算しない）")
    p.add_argument("--ruri", default="cl-nagoya/ruri-v3-130m")
    p.add_argument("--prefix", default="トピック: ", help='"" / "トピック: " / "検索クエリ: "')
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--batch_size", type=int, default=64)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--weight_decay", type=float, default=0.01)
    p.add_argument("--dropout", type=float, default=0.1, help="大きいほど丸暗記しにくい（0.1〜0.3）")
    p.add_argument("--d_model", type=int, default=256, help="モデルの幅。小さいほど覚える力が弱い")
    p.add_argument("--n_layers", type=int, default=2)
    p.add_argument("--d_ff", type=int, default=None, help="FFNの幅（省略時は d_model の2倍）")
    p.add_argument("--schedule", choices=["const", "cosine"], default="const",
                   help="cosine: 最初の warmup_epochs で学習率を上げ、そのあと少しずつ下げる")
    p.add_argument("--warmup_epochs", type=float, default=1.0)
    p.add_argument("--unsafe_pos_weight", type=float, default=1.0,
                   help="危険な発言を見逃したときの損失を何倍にするか（危険かどうかの専用ヘッド）")
    p.add_argument("--no_unsafe_head", action="store_true", help="専用ヘッドを使わない（前の版と同じ作り）")
    p.add_argument("--patience", type=int, default=8, help="検証の損失が下がらないまま何エポックで止めるか")
    p.add_argument("--head_weights", default="{}", help='損失の重み 例: \'{"safety": 2.0}\'')
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--show", type=int, default=5, help="最後に予測を表示する検証データの件数")
    return p.parse_args()


def set_seed(seed):
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def split_rows(rows, ratio, seed):
    idx = list(range(len(rows)))
    random.Random(seed).shuffle(idx)
    n_val = max(1, round(len(rows) * ratio))
    val = set(idx[:n_val])
    return [r for i, r in enumerate(rows) if i not in val], [r for i, r in enumerate(rows) if i in val]


# ---------------------------------------------------------------------------
# 評価
# ---------------------------------------------------------------------------
def _f1(pred, true):
    tp = (pred & true).sum().item()
    fp = (pred & ~true).sum().item()
    fn = (~pred & true).sum().item()
    return None if tp + fp + fn == 0 else 2 * tp / (2 * tp + fp + fn)


def _macro(values):
    values = [v for v in values if v is not None]          # どちらにも出てこないクラスは除く
    return sum(values) / len(values) if values else None


@torch.no_grad()
def evaluate(model, loader, cfg, device):
    model.eval()
    outs, tgts = [], []
    for batch in loader:
        b = {k: v.to(device) for k, v in batch.items()}
        out = model(b["emb"], b["speaker"], b["pad"])
        out.pop("attn")
        outs.append(out)
        tgts.append(b)
    out = {k: torch.cat([o[k] for o in outs]) for k in outs[0]}
    tgt = {k: torch.cat([t[k] for t in tgts]) for k in tgts[0]}
    loss, parts = judge_loss(out, tgt)

    res = {"loss": loss.item(), "parts": parts}
    for head in ("route", "emotion"):                       # 1つを選ぶ判定
        m = tgt[f"mask_{head}"].bool()
        if m.any():
            p, t = out[head][m].argmax(-1), tgt[head][m].argmax(-1)
            res[f"{head}_acc"] = (p == t).float().mean().item()
            res[f"{head}_f1"] = _macro([_f1(p == c, t == c) for c in range(out[head].shape[-1])])
    for head in MULTI_HEADS:                                # 複数可の判定（0.5で区切る）
        m = tgt[f"mask_{head}"].bool()
        if m.any():
            p, t = torch.sigmoid(out[head][m]) > 0.5, tgt[head][m] > 0.5
            res[f"{head}_f1"] = _macro([_f1(p[:, c], t[:, c]) for c in range(p.shape[-1])])
            if head == "safety" and t.any():
                res["safety_recall"] = ((p & t).sum() / t.sum()).item()   # 危険を見逃さないか
    m = tgt["mask_safety"].bool()
    if "unsafe" in out and m.any():                         # 危険かどうかの専用ヘッド（0.5で区切る）
        p = torch.sigmoid(out["unsafe"][m]) > 0.5
        t = tgt["safety"][m].max(-1).values > 0.5
        res["unsafe_f1"] = _f1(p, t)
        if t.any():
            res["unsafe_recall"] = ((p & t).sum() / t.sum()).item()
    m = tgt["mask_style"].bool()
    if m.any():
        res["style_mae"] = (torch.sigmoid(out["style"][m]) - tgt["style"][m]).abs().mean().item()
    m = tgt["mask_intensity"].bool()
    if m.any():
        res["intensity_mae"] = (torch.sigmoid(out["intensity"][m]) - tgt["intensity"][m]).abs().mean().item()

    m = tgt["mask_route"].bool()                            # 振り分けの混同行列
    if m.any():
        n = len(cfg.route_labels)
        cm = torch.zeros(n, n, dtype=torch.long)
        for t, p in zip(tgt["route"][m].argmax(-1).tolist(), out["route"][m].argmax(-1).tolist()):
            cm[t, p] += 1
        res["route_confusion"] = cm.tolist()
    return res


def _fmt(res):
    keys = ["route_acc", "route_f1", "emotion_acc", "intensity_mae", "nature_f1",
            "style_mae", "reaction_f1", "safety_f1", "safety_recall", "unsafe_f1", "unsafe_recall"]
    return "  ".join(f"{k}={res[k]:.3f}" for k in keys if res.get(k) is not None)


def print_confusion(cm, labels):
    print("\n振り分けの混同行列（行=正解, 列=予測）")
    w = max(len(l) for l in labels) * 2
    print(" " * w + "".join(f"{l[:4]:>8s}" for l in labels))
    for l, row in zip(labels, cm):
        print(f"{l:<{w - len(l)}s}" + "".join(f"{v:8d}" for v in row))


# ---------------------------------------------------------------------------
# 予測の表示（データが正しく読めているかを目で確かめる）
# ---------------------------------------------------------------------------
@torch.no_grad()
def show_predictions(model, cfg, ds, n, device):
    if n <= 0:
        return
    print(f"\n検証データの予測（先頭 {min(n, len(ds))} 件）")
    for i in range(min(n, len(ds))):
        item = ds[i]
        out = model(item["emb"][None].to(device), item["speaker"][None].to(device), item["pad"][None].to(device))
        row = ds.rows[i]
        for t in row["turns"]:
            print(f"  {'飼い主' if t['speaker'] in ('owner', '飼い主') else 'ペット'}: {t['text']}")
        emo = out["emotion"].softmax(-1)[0]
        k = int(emo.argmax())
        gold = row.get("labels", {}).get("route", "-")
        print(f"    → {decide(out, cfg)[0]}（正解: {gold}）  "
              f"気持ち: {cfg.emotion_labels[k]} {emo[k]:.2f} / 強さ {torch.sigmoid(out['intensity'])[0]:.2f}")


# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    set_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = JudgeConfig(dropout=args.dropout, d_model=args.d_model, n_layers=args.n_layers,
                      d_ff=args.d_ff or args.d_model * 2, unsafe_head=not args.no_unsafe_head)

    # データ
    rows = load_jsonl(args.train)
    if args.val:
        train_rows, val_rows = rows, load_jsonl(args.val)
    else:
        train_rows, val_rows = split_rows(rows, args.val_ratio, args.seed)
    (out_dir / "split.json").write_text(json.dumps(
        {"train": [r["id"] for r in train_rows], "val": [r["id"] for r in val_rows]},
        ensure_ascii=False, indent=1), encoding="utf-8")

    encoder = RuriEncoder(args.ruri, args.prefix, cache_dir=args.cache_dir, device=device)
    train_ds = JudgeDataset(train_rows, encoder, cfg)
    val_ds = JudgeDataset(val_rows, encoder, cfg)
    test_ds = JudgeDataset(load_jsonl(args.test), encoder, cfg) if args.test else None
    del encoder                                            # 学習中はRuriを使わないのでGPUを空ける
    if device == "cuda":
        torch.cuda.empty_cache()
    print("\n学習データ"); label_summary(train_ds)
    print("検証データ"); label_summary(val_ds)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size)

    # モデル
    model = PetJudge(cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    sched = None
    if args.schedule == "cosine":                          # ウォームアップ → コサインで下げる
        import math
        total = args.epochs * len(train_loader)
        warm = max(1, int(args.warmup_epochs * len(train_loader)))
        sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda step: (step + 1) / warm if step < warm else
                                                  0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * min(1.0, (step - warm) / max(1, total - warm)))))
    weights = json.loads(args.head_weights)
    print(f"\ndevice={device}  パラメータ {sum(p.numel() for p in model.parameters())/1e6:.2f}M  "
          f"prefix={args.prefix!r}  重み={weights or 'なし'}\n")

    history, best, bad = [], float("inf"), 0
    for epoch in range(1, args.epochs + 1):
        model.train()
        t0, total, n = time.time(), 0.0, 0
        for batch in train_loader:
            b = {k: v.to(device) for k, v in batch.items()}
            out = model(b["emb"], b["speaker"], b["pad"])
            loss, _ = judge_loss(out, b, weights, args.unsafe_pos_weight)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            if sched:
                sched.step()
            total += loss.item() * len(b["emb"])
            n += len(b["emb"])

        val = evaluate(model, val_loader, cfg, device)
        history.append({"epoch": epoch, "train_loss": total / n, **{k: v for k, v in val.items() if k != "route_confusion"}})
        mark = ""
        if val["loss"] < best:
            best, bad, mark = val["loss"], 0, " *"
            torch.save({"model": model.state_dict(), "cfg": asdict(cfg), "ruri_model": args.ruri,
                        "prefix": args.prefix, "epoch": epoch, "val": val}, out_dir / "best.pt")
        else:
            bad += 1
        print(f"ep{epoch:3d}  train {total/n:.4f}  val {val['loss']:.4f}{mark}  {_fmt(val)}  ({time.time()-t0:.1f}s)")
        if bad >= args.patience:
            print(f"検証の損失が {args.patience} エポック下がらないので終了")
            break

    (out_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
    try:                                                   # 損失のグラフ（curves.png）
        from plot_history import plot
        print(f"グラフを保存: {plot(out_dir)}")
    except Exception as e:
        print(f"グラフは作れませんでした: {e}")

    # いちばん良かった重みで最終評価
    model, cfg, meta = load_judge(out_dir / "best.pt", device)
    val = evaluate(model, val_loader, cfg, device)
    print(f"\n最良 ep{meta['epoch']}  val {val['loss']:.4f}  {_fmt(val)}")
    if "route_confusion" in val:
        print_confusion(val["route_confusion"], cfg.route_labels)
    show_predictions(model, cfg, val_ds, args.show, device)

    if test_ds is not None:                                # 自分で付けた正解での最終評価
        test = evaluate(model, DataLoader(test_ds, batch_size=args.batch_size), cfg, device)
        print(f"\n==== 評価用データ（{args.test}、{len(test_ds)} 件）====")
        print(f"  {_fmt(test)}")
        if "route_confusion" in test:
            print_confusion(test["route_confusion"], cfg.route_labels)
        (out_dir / "test.json").write_text(json.dumps(test, ensure_ascii=False, indent=1), encoding="utf-8")

    # 比べるための1行まとめ（summary.json にも保存）
    summary = {"run": out_dir.name, "best_epoch": meta["epoch"], "val_loss": round(val["loss"], 4),
               "val_route_acc": round(val.get("route_acc", 0), 3), "val_reaction_f1": round(val.get("reaction_f1") or 0, 3),
               "val_safety_recall": round(val.get("safety_recall") or 0, 3),
               "val_unsafe_recall": round(val.get("unsafe_recall") or 0, 3),
               "settings": {k: getattr(args, k) for k in ("dropout", "weight_decay", "lr", "d_model", "n_layers", "schedule", "seed")}}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n保存先: {out_dir}")


if __name__ == "__main__":
    main()