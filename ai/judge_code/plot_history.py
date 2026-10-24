"""
plot_history.py — 学習の記録（history.json）をグラフにする

  python plot_history.py --run_dir /content/drive/MyDrive/jphacks/pet_ai/judge/v1
  → run_dir/curves.png

train_judge.py の最後にも自動で呼ばれる。
Colab に日本語フォントが無く文字化けするので、グラフ内の文字は英語にしている。

グラフは3枚:
  1. Loss          : 学習データと検証データの損失（下がるほど良い）。★が保存したエポック
  2. Validation    : 検証データでの正解率・F1（上がるほど良い）
  3. Loss by head  : 検証データの損失をヘッドごとに分けたもの（どこが足を引っ張っているか）
"""
import argparse
import json
from pathlib import Path

# 色はヘッドやシリーズごとに固定（順番を変えない）
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#8a5cd1", "#5c5c58"]
INK, MUTED, GRID = "#2b2b29", "#76756f", "#e4e3de"

METRICS = [("route_acc", "route acc"), ("route_f1", "route F1"), ("emotion_acc", "emotion acc"),
           ("safety_f1", "safety F1"), ("reaction_f1", "reaction F1"), ("nature_f1", "nature F1"),
           ("unsafe_f1", "unsafe F1")]
HEADS = ["route", "emotion", "intensity", "nature", "style", "reaction", "safety", "unsafe"]


def _style(ax, title, ylabel):
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold")
    ax.set_xlabel("epoch", color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)


def _line(ax, x, y, color, label):
    pts = [(a, b) for a, b in zip(x, y) if b is not None]
    if not pts:
        return False
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=2, label=label, marker="o" if len(xs) <= 30 else None,
            markersize=4, markeredgecolor="white", markeredgewidth=1)
    return True


def plot(run_dir, out=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    run_dir = Path(run_dir)
    hist = json.loads((run_dir / "history.json").read_text(encoding="utf-8"))
    if not hist:
        raise SystemExit("history.json が空です")
    ep = [h["epoch"] for h in hist]
    best = min(hist, key=lambda h: h["loss"])

    fig, axes = plt.subplots(1, 3, figsize=(16, 5), dpi=110)
    fig.patch.set_facecolor("white")

    # 1. 損失
    ax = axes[0]
    _line(ax, ep, [h["train_loss"] for h in hist], C[0], "train")
    _line(ax, ep, [h["loss"] for h in hist], C[1], "validation")
    ax.axvline(best["epoch"], color=MUTED, linestyle="--", linewidth=1)
    ax.plot([best["epoch"]], [best["loss"]], marker="*", markersize=14, color=C[1],
            markeredgecolor="white", markeredgewidth=1, zorder=5)
    ax.annotate(f"saved: ep{best['epoch']}\nval {best['loss']:.3f}", (best["epoch"], best["loss"]),
                textcoords="offset points", xytext=(8, 12), fontsize=8, color=INK)
    _style(ax, "Loss (lower is better)", "loss")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)

    # 2. 検証データの正解率・F1
    ax = axes[1]
    drawn = [_line(ax, ep, [h.get(k) for h in hist], C[i], name) for i, (k, name) in enumerate(METRICS)]
    ax.axvline(best["epoch"], color=MUTED, linestyle="--", linewidth=1)
    ax.set_ylim(0, 1.02)
    _style(ax, "Validation score (higher is better)", "accuracy / F1")
    if any(drawn):
        ax.legend(frameon=False, fontsize=8, labelcolor=INK, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.16))

    # 3. ヘッドごとの検証損失
    ax = axes[2]
    drawn = [_line(ax, ep, [h.get("parts", {}).get(k) for h in hist], C[i], k) for i, k in enumerate(HEADS)]
    ax.axvline(best["epoch"], color=MUTED, linestyle="--", linewidth=1)
    _style(ax, "Validation loss by head", "loss")
    if any(drawn):
        ax.legend(frameon=False, fontsize=8, labelcolor=INK, ncol=4, loc="upper left", bbox_to_anchor=(0, -0.16))

    fig.tight_layout()
    out = Path(out) if out else run_dir / "curves.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    _show(out)
    return out


def _show(path):
    """ノートブック（%run）で動いているときは、セルの出力にグラフを表示する"""
    try:
        from IPython import get_ipython
        from IPython.display import Image, display
        if get_ipython() is not None and getattr(get_ipython(), "kernel", None) is not None:
            display(Image(str(path)))
    except Exception:
        pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run_dir", required=True, help="train_judge.py の --out_dir")
    p.add_argument("--out", default=None)
    a = p.parse_args()
    print(f"保存しました → {plot(a.run_dir, a.out)}")