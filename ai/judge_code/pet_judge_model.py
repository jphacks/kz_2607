"""
pet_judge_model.py — 手順3-1：自作Transformer（会話の判定モデル）の本体

Ruri v3（130m、512次元、固定）の文ベクトルを最大4発言ぶん並べて読み、
6つのヘッド（振り分け・気持ち・発言の性質・話し方・反応の仕方・安全）で判定する。

この段階で作るのは「モデル定義」と「動作確認」だけ。
  - Ruri の読み込み・ベクトルのキャッシュ → 手順3-2
  - 学習データ・学習ループ               → 手順3-3 以降

Colab での実行:  !python pet_judge_model.py   （CPUでも数十秒で終わる）
"""
from dataclasses import dataclass
import math

import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# 設定（ヘッドの種類は未決事項なので、ラベルの並びはここだけ変えればよい）
# ---------------------------------------------------------------------------
@dataclass
class JudgeConfig:
    emb_dim: int = 512          # Ruri v3 130m の出力次元
    d_model: int = 256
    n_layers: int = 2
    n_heads: int = 4
    d_ff: int = 512
    dropout: float = 0.1
    max_turns: int = 4          # 直前3発言＋今の発言
    n_speakers: int = 2         # 0=飼い主, 1=ペット

    route_labels: tuple = ("雑談", "思い出", "ペット自身", "込み入った質問")
    emotion_labels: tuple = ("喜び", "怒り", "悲しみ", "不安", "驚き")   # 特に気持ちが無い発言はラベルを付けない
    nature_labels: tuple = ("理屈", "感覚", "質問")          # 複数可
    style_labels: tuple = ("敬語", "関西弁")                # 0〜1 の度合い
    reaction_labels: tuple = ("共感", "ツッコミ", "ボケ", "褒める")  # 複数可
    safety_labels: tuple = ("暴言", "差別", "性的")          # 複数可。全部低ければ安全
    unsafe_head: bool = True    # 「危険かどうか」だけを判定する専用ヘッド（種類は safety ヘッドで記録用に判定）


# ---------------------------------------------------------------------------
# Transformer の部品（Week1 の Attention を PyTorch で書き直したもの）
# ---------------------------------------------------------------------------
class SelfAttention(nn.Module):
    def __init__(self, cfg: JudgeConfig):
        super().__init__()
        assert cfg.d_model % cfg.n_heads == 0
        self.h = cfg.n_heads
        self.dk = cfg.d_model // cfg.n_heads
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model)
        self.out = nn.Linear(cfg.d_model, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)

    def forward(self, x, pad_mask):
        # x: (B, T, D)  pad_mask: (B, T)  True = 空き（発言なし）
        B, T, D = x.shape
        q, k, v = self.qkv(x).chunk(3, dim=-1)
        q = q.view(B, T, self.h, self.dk).transpose(1, 2)        # (B, h, T, dk)
        k = k.view(B, T, self.h, self.dk).transpose(1, 2)
        v = v.view(B, T, self.h, self.dk).transpose(1, 2)

        scores = q @ k.transpose(-2, -1) / math.sqrt(self.dk)    # (B, h, T, T)
        # 空きの発言は見ない。今の発言は必ずあるので、どの行も全部 -inf にはならない
        scores = scores.masked_fill(pad_mask[:, None, None, :], float("-inf"))
        attn = scores.softmax(dim=-1)
        y = (self.drop(attn) @ v).transpose(1, 2).reshape(B, T, D)
        return self.out(y), attn                                  # attn は観察用に返す


class Block(nn.Module):
    """Pre-LN の Transformer ブロック"""
    def __init__(self, cfg: JudgeConfig):
        super().__init__()
        d = cfg.d_model
        self.ln1 = nn.LayerNorm(d)
        self.attn = SelfAttention(cfg)
        self.ln2 = nn.LayerNorm(d)
        self.ff = nn.Sequential(
            nn.Linear(d, cfg.d_ff), nn.GELU(), nn.Dropout(cfg.dropout), nn.Linear(cfg.d_ff, d)
        )
        self.drop = nn.Dropout(cfg.dropout)

    def forward(self, x, pad_mask):
        a, w = self.attn(self.ln1(x), pad_mask)
        x = x + self.drop(a)
        x = x + self.drop(self.ff(self.ln2(x)))
        return x, w


# ---------------------------------------------------------------------------
# 判定モデル本体
# ---------------------------------------------------------------------------
class PetJudge(nn.Module):
    """
    入力は「右詰め」で並べる。いちばん右（index T-1）が今の発言。
      emb:      (B, T, 512)  Ruri のベクトル（空きは0でよい）
      speaker:  (B, T)       0=飼い主, 1=ペット（空きは0でよい）
      pad_mask: (B, T)       True=空き
    位置の目印は「何番目か」ではなく「何発言前か」（0=今, 1=1つ前 ...）。
    こうすると会話が短くても今の発言はいつも同じ目印になる。
    """
    def __init__(self, cfg: JudgeConfig = JudgeConfig()):
        super().__init__()
        self.cfg = cfg
        d = cfg.d_model
        self.in_proj = nn.Sequential(nn.LayerNorm(cfg.emb_dim), nn.Linear(cfg.emb_dim, d))
        self.speaker_emb = nn.Embedding(cfg.n_speakers, d)
        self.dist_emb = nn.Embedding(cfg.max_turns, d)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layers))
        self.ln_f = nn.LayerNorm(d)

        n_emo = len(cfg.emotion_labels)
        self.heads = nn.ModuleDict({
            "route":    nn.Linear(d, len(cfg.route_labels)),
            "emotion":  nn.Linear(d, n_emo + 1),          # 気持ち + 強さ
            "nature":   nn.Linear(d, len(cfg.nature_labels)),
            "style":    nn.Linear(d, len(cfg.style_labels)),
            "reaction": nn.Linear(d, len(cfg.reaction_labels)),
            "safety":   nn.Linear(d, len(cfg.safety_labels)),
        })
        if cfg.unsafe_head:
            self.heads["unsafe"] = nn.Linear(d, 1)
        # 危険な発言はごく一部なので、最初は「ほぼ安全（約12%）」から学習を始める
        for name in ("safety", "unsafe"):
            if name in self.heads:
                nn.init.constant_(self.heads[name].bias, -2.0)

    def forward(self, emb, speaker, pad_mask):
        B, T, _ = emb.shape
        assert T <= self.cfg.max_turns
        dist = torch.arange(T - 1, -1, -1, device=emb.device)    # [T-1, ..., 1, 0]
        x = self.in_proj(emb) + self.speaker_emb(speaker) + self.dist_emb(dist)[None]

        attns = []
        for blk in self.blocks:
            x, w = blk(x, pad_mask)
            attns.append(w)

        h = self.ln_f(x[:, -1])                                    # 今の発言の位置だけ読む
        out = {name: head(h) for name, head in self.heads.items()}
        emo = out.pop("emotion")
        out["emotion"] = emo[:, :-1]                               # logits
        out["intensity"] = emo[:, -1]                              # logit（sigmoid で 0〜1）
        if "unsafe" in out:
            out["unsafe"] = out["unsafe"].squeeze(-1)              # (B,) 危険かどうかの logit
        out["attn"] = attns                                        # 層ごと (B, h, T, T)
        return out


# ---------------------------------------------------------------------------
# 損失（ラベルが無いヘッドはその例だけ学習しない）
# ---------------------------------------------------------------------------
def judge_loss(out, tgt, weights=None, unsafe_pos_weight=1.0):
    """
    tgt（無い項目はスキップ）:
      route (B,4) / emotion (B,8) : 確率。やわらかい正解はそのまま、硬い正解は one-hot
      intensity (B,)              : 0〜1
      nature / reaction / safety  : 0〜1（複数可）
      style (B,2)                 : 0〜1 の度合い
      mask_<名前> (B,)            : 1=この例でそのヘッドを学習する（省略時は全部1）
    """
    weights = weights or {}
    losses = {}

    def masked_mean(per_example, name):
        m = tgt.get(f"mask_{name}", torch.ones_like(per_example))
        return (per_example * m).sum() / m.sum().clamp(min=1)

    for name in ("route", "emotion"):                              # 1つを選ぶ判定
        if name in tgt:
            l = F.cross_entropy(out[name], tgt[name], reduction="none")
            losses[name] = masked_mean(l, name)

    for name in ("nature", "reaction", "safety"):                  # 複数可の判定
        if name in tgt:
            l = F.binary_cross_entropy_with_logits(out[name], tgt[name], reduction="none").mean(-1)
            losses[name] = masked_mean(l, name)

    if "unsafe" in out and "safety" in tgt:                        # 危険かどうか（どれか1つでも危険なら1）
        y = tgt["safety"].max(-1).values
        pw = torch.tensor(unsafe_pos_weight, device=y.device)     # 見逃したときの損失を何倍にするか
        l = F.binary_cross_entropy_with_logits(out["unsafe"], y, pos_weight=pw, reduction="none")
        losses["unsafe"] = masked_mean(l, "safety")

    if "style" in tgt:                                             # 度合い
        l = F.mse_loss(torch.sigmoid(out["style"]), tgt["style"], reduction="none").mean(-1)
        losses["style"] = masked_mean(l, "style")
    if "intensity" in tgt:
        l = F.mse_loss(torch.sigmoid(out["intensity"]), tgt["intensity"], reduction="none")
        losses["intensity"] = masked_mean(l, "intensity")

    total = sum(weights.get(k, 1.0) * v for k, v in losses.items())
    return total, {k: v.item() for k, v in losses.items()}


# ---------------------------------------------------------------------------
# 判定に自信がないときのルール（進捗資料の「判定に自信がないとき」をそのまま実装）
# ---------------------------------------------------------------------------
def unsafe_prob(out):
    """危険らしさ（0〜1）。専用ヘッドがあればそれ、無ければ3種類のうち最大"""
    if "unsafe" in out:
        return torch.sigmoid(out["unsafe"])
    return torch.sigmoid(out["safety"]).max(-1).values


@torch.no_grad()
def decide(out, cfg: JudgeConfig, confident=0.6, unsafe=0.5, chat_memory_margin=0.15):
    R = cfg.route_labels
    i_chat, i_mem, i_api = R.index("雑談"), R.index("思い出"), R.index("込み入った質問")
    p_route = out["route"].softmax(-1)
    p_unsafe = unsafe_prob(out)

    results = []
    for p, s in zip(p_route, p_unsafe):
        if s >= unsafe:                                            # 安全が最優先
            results.append("安全な返事")
            continue
        top = int(p.argmax())
        if top == i_api and p[i_api] < confident:                  # API か迷ったら自作モデル
            p2 = p.clone(); p2[i_api] = -1
            top = int(p2.argmax())
        if top in (i_chat, i_mem) and abs(p[i_chat] - p[i_mem]) < chat_memory_margin:
            results.append("思い出（検索して無ければ雑談）")    # 雑談か思い出か迷ったら検索
            continue
        results.append(R[top])
    return results


# ---------------------------------------------------------------------------
# 保存した重みの読み込み（train_judge.py が保存した best.pt を読む）
# ---------------------------------------------------------------------------
class JudgeEnsemble(nn.Module):
    """同じ作りのモデルを何個か（シードだけ違う）まとめ、出力（ロジット）を平均する。
    1つずつだと学習の運で数件ずつ答えが揺れるので、平均してならす"""

    def __init__(self, models):
        super().__init__()
        self.models = nn.ModuleList(models)

    def forward(self, *args, **kwargs):
        outs = [m(*args, **kwargs) for m in self.models]
        return {k: torch.stack([o[k] for o in outs]).mean(0) if torch.is_tensor(outs[0][k]) else outs[0][k]
                for k in outs[0]}                                  # attn（リスト）は1つ目のものを返す


def load_judge(path, device="cpu"):
    """path に「a.pt+b.pt+c.pt」と + でつなぐと、まとめて平均するモデルとして読む"""
    path = str(path)
    if "+" in path:
        parts = [load_judge(p.strip(), device) for p in path.split("+")]
        model = JudgeEnsemble([m for m, _, _ in parts]).to(device).eval()
        return model, parts[0][1], parts[0][2]
    ckpt = torch.load(path, map_location=device)
    c = dict(ckpt["cfg"])
    c["unsafe_head"] = "heads.unsafe.weight" in ckpt["model"]   # 専用ヘッドが無い古い版も読めるように
    cfg = JudgeConfig(**{k: tuple(v) if isinstance(v, list) else v for k, v in c.items()})
    model = PetJudge(cfg).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    meta = {k: v for k, v in ckpt.items() if k not in ("model", "cfg")}
    return model, cfg, meta


# ---------------------------------------------------------------------------
# 動作確認
# ---------------------------------------------------------------------------
def _random_batch(B, T, cfg, n_real=None, device="cpu"):
    """右詰めのダミー入力。n_real[i] = その例の実際の発言数"""
    emb = torch.randn(B, T, cfg.emb_dim, device=device)
    speaker = torch.randint(0, cfg.n_speakers, (B, T), device=device)
    speaker[:, -1] = 0                                             # 今の発言は飼い主
    if n_real is None:
        n_real = torch.randint(1, T + 1, (B,))
    pad = torch.arange(T)[None, :] < (T - n_real)[:, None]         # 左側が空き
    return emb, speaker, pad.to(device)


def check_shapes(cfg, device):
    model = PetJudge(cfg).to(device).eval()
    emb, spk, pad = _random_batch(5, cfg.max_turns, cfg, device=device)
    out = model(emb, spk, pad)
    print("[1] 出力の形")
    for k, v in out.items():
        if k != "attn":
            print(f"    {k:9s} {tuple(v.shape)}")
    print(f"    attn      {len(out['attn'])}層 × {tuple(out['attn'][0].shape)}")
    n = sum(p.numel() for p in model.parameters())
    print(f"    パラメータ数: {n/1e6:.2f}M")


def check_padding(cfg, device):
    """空きの中身を変えても結果が変わらないこと（マスクが効いているか）"""
    model = PetJudge(cfg).to(device).eval()
    emb, spk, pad = _random_batch(4, cfg.max_turns, cfg, n_real=torch.tensor([1, 2, 3, 4]), device=device)
    a = model(emb, spk, pad)["route"]
    emb2 = emb.clone()
    emb2[pad] = torch.randn_like(emb2[pad]) * 100                  # 空きにゴミを入れる
    b = model(emb2, spk, pad)["route"]
    diff = (a - b).abs().max().item()
    print(f"[2] 空きを書き換えたときの差: {diff:.2e}  →  {'OK' if diff < 1e-4 else 'NG'}")


def check_context(cfg, device, steps=400):
    """
    「1つ前の発言を見ないと分からない」人工の課題で、文脈を読めているかを見る。
    正解 = 1つ前の発言がある方向 u を向いているか（思い出 / 雑談）。
    今の発言だけ渡したモデルは 50% 前後に留まるはず。
    """
    torch.manual_seed(0)
    u = torch.randn(cfg.emb_dim, device=device)

    def make(B):
        emb, spk, pad = _random_batch(B, cfg.max_turns, cfg, n_real=torch.full((B,), cfg.max_turns), device=device)
        y = (emb[:, -2] @ u > 0).long()                            # 1つ前の発言で決まる
        tgt = F.one_hot(torch.where(y == 1, 1, 0), len(cfg.route_labels)).float()
        return emb, spk, pad, tgt, y

    def run(use_context):
        model = PetJudge(cfg).to(device)
        opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
        for _ in range(steps):
            emb, spk, pad, tgt, _ = make(128)
            if not use_context:
                emb, spk, pad = emb[:, -1:], spk[:, -1:], pad[:, -1:]
            loss, _ = judge_loss(model(emb, spk, pad), {"route": tgt})
            opt.zero_grad(); loss.backward(); opt.step()
        model.eval()
        with torch.no_grad():
            emb, spk, pad, _, y = make(2000)
            if not use_context:
                emb, spk, pad = emb[:, -1:], spk[:, -1:], pad[:, -1:]
            pred = model(emb, spk, pad)["route"].argmax(-1)
            pred = (pred == 1).long()
            return (pred == y).float().mean().item()

    acc_ctx, acc_now = run(True), run(False)
    print(f"[3] 文脈が必要な課題の正解率  4発言: {acc_ctx:.1%}  今の発言だけ: {acc_now:.1%}")
    print(f"    →  {'OK' if acc_ctx > 0.9 and acc_now < 0.6 else '要確認'}")


def check_decide(cfg, device):
    model = PetJudge(cfg).to(device).eval()
    emb, spk, pad = _random_batch(3, cfg.max_turns, cfg, device=device)
    print("[4] decide() の出力例（未学習なので中身に意味はない）:", decide(model(emb, spk, pad), cfg))


if __name__ == "__main__":
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cfg = JudgeConfig()
    print(f"device = {device}\n")
    check_shapes(cfg, device)
    check_padding(cfg, device)
    check_context(cfg, device)
    check_decide(cfg, device)