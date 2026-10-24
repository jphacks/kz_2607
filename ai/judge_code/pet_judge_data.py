"""
pet_judge_data.py — 手順3-2：学習データの読み込みと Ruri v3 によるベクトル化

■ データの形式（JSONL：1行に1会話）

{"id": "s001",
 "turns": [
   {"speaker": "pet",   "text": "きのう公園でボール遊びしたね！"},
   {"speaker": "owner", "text": "それ覚えてる？めっちゃ楽しかったやつ"}
 ],
 "labels": {
   "route":     "思い出",                        ← 1つを選ぶ。迷う例は {"思い出": 0.7, "雑談": 0.3}
   "emotion":   "喜び",                          ← 同上
   "intensity": 0.6,                            ← 気持ちの強さ 0〜1
   "nature":    ["質問"],                        ← 当てはまるものを全部（無ければ []）
   "style":     {"敬語": 0.0, "関西弁": 0.6},     ← 全項目を 0〜1 で
   "reaction":  ["共感"],                        ← 当てはまるものを全部
   "safety":    []                              ← 危険なものを全部。安全なら []
 }}

- turns は古い順に 1〜4 発言。最後の発言が「判定する発言」で、必ず飼い主（owner）。
- speaker は owner / pet（「飼い主」「ペット」でも可）。
- labels は書いた項目だけ学習に使う。付けていない項目はその例では学習しない。
  （例：振り分けのデータだけ先に集める、といった使い方ができる）
- safety の [] は「安全」という正解。項目ごと書かないのとは意味が違う。
- ラベル名は pet_judge_model.py の JudgeConfig と一致させる。
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import torch
from torch.utils.data import Dataset

from pet_judge_model import JudgeConfig

SPEAKER_IDS = {"owner": 0, "飼い主": 0, "pet": 1, "ペット": 1}

# ヘッド名 → (JudgeConfig のラベル一覧, 種類)
#   single: 1つを選ぶ（確率）  multi: 複数可（0〜1）  degree: 全項目の度合い（0〜1）
HEAD_KINDS = {
    "route":    ("route_labels", "single"),
    "emotion":  ("emotion_labels", "single"),
    "nature":   ("nature_labels", "multi"),
    "style":    ("style_labels", "degree"),
    "reaction": ("reaction_labels", "multi"),
    "safety":   ("safety_labels", "multi"),
}

PREFIX_TAGS = {"": "plain", "トピック: ": "topic", "検索クエリ: ": "query", "検索文書: ": "doc"}


# ---------------------------------------------------------------------------
# 読み込みとチェック
# ---------------------------------------------------------------------------
def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path} の {n} 行目がJSONとして読めません: {e}") from None
            row.setdefault("id", f"{Path(path).stem}:{n}")
            rows.append(row)
    return rows


def _index(name, names):
    if name not in names:
        raise ValueError(f"「{name}」は {list(names)} にありません")
    return names.index(name)


def _to_vector(value, names, kind):
    v = torch.zeros(len(names))
    if kind == "single":
        if isinstance(value, str):
            v[_index(value, names)] = 1.0
        elif isinstance(value, dict):
            for k, p in value.items():
                v[_index(k, names)] = float(p)
            if v.sum() <= 0:
                raise ValueError("確率の合計が0です")
            v /= v.sum()                       # 合計が1でなくても割合として扱う
        else:
            raise ValueError(f"文字列か {{ラベル: 確率}} で書いてください: {value!r}")
    elif kind == "multi":
        if isinstance(value, list):
            for k in value:
                v[_index(k, names)] = 1.0
        elif isinstance(value, dict):
            for k, p in value.items():
                v[_index(k, names)] = float(p)
        else:
            raise ValueError(f"リストか {{ラベル: 0〜1}} で書いてください: {value!r}")
    elif kind == "degree":
        if not isinstance(value, dict) or set(value) != set(names):
            raise ValueError(f"{list(names)} をすべて 0〜1 で書いてください: {value!r}")
        for k, p in value.items():
            v[_index(k, names)] = float(p)
    if ((v < 0) | (v > 1)).any():
        raise ValueError(f"0〜1 の範囲外の値があります: {value!r}")
    return v


def parse_row(row, cfg: JudgeConfig):
    """1会話をチェックし、正解とマスクの dict にする"""
    turns = row.get("turns") or []
    if not 1 <= len(turns) <= cfg.max_turns:
        raise ValueError(f"turns は 1〜{cfg.max_turns} 発言にしてください（{len(turns)} 発言）")
    for t in turns:
        if t.get("speaker") not in SPEAKER_IDS:
            raise ValueError(f"speaker は {list(SPEAKER_IDS)} のどれかにしてください: {t.get('speaker')!r}")
        if not str(t.get("text", "")).strip():
            raise ValueError("空の発言があります")
    if SPEAKER_IDS[turns[-1]["speaker"]] != 0:
        raise ValueError("最後の発言（判定する発言）は飼い主にしてください")

    labels = row.get("labels") or {}
    unknown = set(labels) - set(HEAD_KINDS) - {"intensity"}
    if unknown:
        raise ValueError(f"知らないラベル名があります: {sorted(unknown)}")

    tgt = {}
    for head, (attr, kind) in HEAD_KINDS.items():
        names = list(getattr(cfg, attr))
        if labels.get(head) is not None:
            try:
                tgt[head] = _to_vector(labels[head], names, kind)
            except ValueError as e:
                raise ValueError(f"{head}: {e}") from None
            tgt[f"mask_{head}"] = torch.tensor(1.0)
        else:
            tgt[head] = torch.zeros(len(names))
            tgt[f"mask_{head}"] = torch.tensor(0.0)

    if labels.get("intensity") is not None:
        x = float(labels["intensity"])
        if not 0 <= x <= 1:
            raise ValueError(f"intensity は 0〜1 にしてください: {x}")
        tgt["intensity"], tgt["mask_intensity"] = torch.tensor(x), torch.tensor(1.0)
    else:
        tgt["intensity"], tgt["mask_intensity"] = torch.tensor(0.0), torch.tensor(0.0)
    return tgt


def validate_rows(rows, cfg: JudgeConfig, max_show=20):
    """全行をチェックし、問題があればまとめて報告する"""
    parsed, errors = [], []
    for row in rows:
        try:
            parsed.append(parse_row(row, cfg))
        except ValueError as e:
            errors.append(f"  [{row.get('id')}] {e}")
    if errors:
        shown = "\n".join(errors[:max_show])
        more = f"\n  ...ほか {len(errors) - max_show} 件" if len(errors) > max_show else ""
        raise ValueError(f"データに {len(errors)} 件の問題があります:\n{shown}{more}")
    return parsed


# ---------------------------------------------------------------------------
# Ruri v3 で文をベクトルにする（結果はキャッシュして Drive に残す）
# ---------------------------------------------------------------------------
class RuriEncoder:
    def __init__(self, model_name="cl-nagoya/ruri-v3-130m", prefix="トピック: ",
                 cache_dir=None, device=None, batch_size=64):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, device=device)
        get_dim = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dim = get_dim()
        self.prefix = prefix
        self.batch_size = batch_size

        # モデルとプレフィックスごとに別のキャッシュにする（混ざると比較できなくなる）
        self.cache_path = None
        self.cache = {}
        if cache_dir:
            tag = PREFIX_TAGS.get(prefix, hashlib.md5(prefix.encode()).hexdigest()[:8])
            name = model_name.replace("/", "__")
            self.cache_path = Path(cache_dir) / f"{name}__{tag}.pt"
            if self.cache_path.exists():
                self.cache = torch.load(self.cache_path)
                print(f"キャッシュを読み込み: {len(self.cache)} 文  ({self.cache_path})")

    @staticmethod
    def _key(text):
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    @torch.no_grad()
    def encode(self, texts):
        need = [t for t in dict.fromkeys(texts) if self._key(t) not in self.cache]
        if need:
            vecs = self.model.encode(
                [self.prefix + t for t in need],
                batch_size=self.batch_size,
                convert_to_tensor=True,
                normalize_embeddings=True,
                show_progress_bar=len(need) > 256,
            ).float().cpu()
            for t, v in zip(need, vecs):
                self.cache[self._key(t)] = v
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                torch.save(self.cache, self.cache_path)
            print(f"Ruriでベクトル化: 新しく {len(need)} 文（キャッシュ合計 {len(self.cache)} 文）")
        return torch.stack([self.cache[self._key(t)] for t in texts])


# ---------------------------------------------------------------------------
# Dataset（ベクトル化は最初に1回だけ。学習中は Ruri を動かさない）
# ---------------------------------------------------------------------------
class JudgeDataset(Dataset):
    def __init__(self, rows, encoder: RuriEncoder, cfg: JudgeConfig):
        if encoder.dim != cfg.emb_dim:
            raise ValueError(f"Ruriの出力 {encoder.dim} 次元と cfg.emb_dim {cfg.emb_dim} が合いません")
        self.rows, self.cfg = rows, cfg
        targets = validate_rows(rows, cfg)

        texts = list(dict.fromkeys(t["text"] for r in rows for t in r["turns"]))
        vecs = encoder.encode(texts)
        where = {t: i for i, t in enumerate(texts)}

        N, T = len(rows), cfg.max_turns
        self.emb = torch.zeros(N, T, cfg.emb_dim)
        self.speaker = torch.zeros(N, T, dtype=torch.long)
        self.pad = torch.ones(N, T, dtype=torch.bool)
        for i, r in enumerate(rows):
            off = T - len(r["turns"])                     # 右詰め：最後が今の発言
            for j, t in enumerate(r["turns"]):
                self.emb[i, off + j] = vecs[where[t["text"]]]
                self.speaker[i, off + j] = SPEAKER_IDS[t["speaker"]]
                self.pad[i, off + j] = False
        self.targets = {k: torch.stack([tg[k] for tg in targets]) for k in targets[0]}

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        item = {"emb": self.emb[i], "speaker": self.speaker[i], "pad": self.pad[i]}
        item.update({k: v[i] for k, v in self.targets.items()})
        return item


def label_summary(ds: JudgeDataset):
    """ヘッドごとに何件ラベルがあるか、振り分けの内訳を表示する（データ集めの目安）"""
    cfg = ds.cfg
    print(f"  会話数: {len(ds)}  発言数の内訳: {dict(sorted(Counter((~ds.pad).sum(1).tolist()).items()))}")
    for head in list(HEAD_KINDS) + ["intensity"]:
        print(f"  {head:9s} ラベルあり {int(ds.targets[f'mask_{head}'].sum()):5d} 件")
    m = ds.targets["mask_route"].bool()
    if m.any():
        counts = Counter(ds.targets["route"][m].argmax(-1).tolist())
        print("  振り分けの内訳: " + "  ".join(f"{n}={counts.get(i, 0)}" for i, n in enumerate(cfg.route_labels)))
