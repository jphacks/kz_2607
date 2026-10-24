"""
mem_embed.py — 近さを測る（Ruri v3。読めなければ文字の重なり）。判定モデルの Ruri を使い回す
"""
import threading
import re
import unicodedata
from typing import Any, Dict, List, Tuple

import mem_config as C
from common import norm

# ---------------------------------------------------------------- 近さ（Ruri v3 → 文字の重なり）
FILLER_RE = re.compile(r"覚えてる|おぼえてる|覚えて|思い出|おもいで|っけ|のこと|ことって|って|なに|何|なん|した|してた|"
                       r"一緒に|いっしょに|話|はなし|ねえ|ね|よね|かな|[？?！!。、\s]")


def _bigrams(s: str) -> set:
    s = re.sub(r"[\s、。！？!?「」『』]", "", norm(s))
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else ({s} if s else set())


def lexical_sim(query: str, doc: str) -> float:
    """今の発言（よくある言葉を除く）の2文字の組が、思い出にどれだけ入っているか（0〜1）。"""
    q = _bigrams(FILLER_RE.sub("", unicodedata.normalize("NFKC", query)))
    if not q:
        return 0.0
    return len(q & _bigrams(doc)) / len(q)


class Embedder:
    """Ruri v3 で文をベクトルにする。思い出のベクトルは id＋text をキーにメモリ上だけで持つ（DB には保存しない）。"""

    def __init__(self, model_name: str = C.RURI_MODEL, mode: str = C.MEMORY_RURI):
        self.model_name, self.mode = model_name, mode
        self.kind = None            # "judge-st"・"judge"・"own-st"・"own-hf"・"lexical"
        self.st = self.tok = self.model = None
        self.cache: Dict[Tuple[str, str], Any] = {}
        self.status = "未読み込み"
        self.lock = threading.Lock()   # 同時に来たとき、Ruri（判定と共有のことも）とキャッシュを1件ずつ使う

    # ---- 判定モデルの Ruri を使い回す
    def attach(self, runner) -> bool:
        if self.mode not in ("auto", "judge") or runner is None:
            return False
        names = ("runner", "encoder", "ruri", "enc", "embedder", "text_encoder", "ruri_encoder")
        cands = [runner] + [getattr(runner, n, None) for n in names]
        cands += [getattr(c, n, None) for c in list(cands) if c is not None for n in names]   # 2段目まで
        for obj in cands:
            if obj is None:
                continue
            # judge_infer.PetJudgeRunner は Ruri を SentenceTransformer（.ruri）で持っている。
            # SentenceTransformer には .model が無いので、下の tokenizer＋model の探し方では見つからない
            if type(obj).__name__ == "SentenceTransformer" and callable(getattr(obj, "encode", None)):
                self.st, self.kind = obj, "judge-st"
                self.status = "判定モデルの Ruri を使い回す（SentenceTransformer）"
                return True
            tok = getattr(obj, "tokenizer", None) or getattr(obj, "tok", None)
            model = getattr(obj, "model", None) or getattr(obj, "backbone", None) or getattr(obj, "encoder", None)
            if tok is not None and model is not None and hasattr(model, "forward") and callable(tok):
                self.tok, self.model, self.kind = tok, model, "judge"
                self.status = f"判定モデルの Ruri を使い回す（{type(obj).__name__}）"
                return True
        self.status = "判定モデルの Ruri が見つからない"
        return False

    # ---- 自分で読む
    def load(self):
        if self.kind:
            return
        if self.mode == "lexical":
            self.kind, self.status = "lexical", "文字の重なり（MEMORY_RURI=lexical）"
            return
        errs = []
        try:
            from sentence_transformers import SentenceTransformer
            self.st = SentenceTransformer(self.model_name)
            self.kind, self.status = "own-st", f"{self.model_name}（sentence-transformers）"
            return
        except Exception as e:
            errs.append(f"st: {type(e).__name__}: {e}")
        try:
            import torch  # noqa: F401
            from transformers import AutoModel, AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModel.from_pretrained(self.model_name).eval()
            self.kind, self.status = "own-hf", f"{self.model_name}（transformers・平均）"
            return
        except Exception as e:
            errs.append(f"hf: {type(e).__name__}: {e}")
        self.kind, self.status = "lexical", "文字の重なり（Ruri が読めない: " + " / ".join(errs)[:300] + "）"

    @property
    def min_sim(self) -> float:
        return C.MEMORY_MIN_LEX if self.kind == "lexical" else C.MEMORY_MIN_SIM

    def _encode(self, texts: List[str]):
        import numpy as np
        if self.kind in ("own-st", "judge-st"):
            v = self.st.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
            return np.asarray(v, dtype="float32")
        import torch
        dev = next(self.model.parameters()).device
        enc = self.tok(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
        enc = {k: v.to(dev) for k, v in enc.items() if k in ("input_ids", "attention_mask", "token_type_ids")}
        with torch.no_grad():
            out = self.model(**enc)
            h = out.last_hidden_state if hasattr(out, "last_hidden_state") else out[0]
            m = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
            v = (h * m).sum(1) / m.sum(1).clamp(min=1)
            v = torch.nn.functional.normalize(v.float(), dim=-1)
        return v.cpu().numpy()

    def scores(self, query: str, docs: List[Tuple[str, str]]) -> List[float]:
        """docs = [(キー, 文)]。返り値は docs と同じ順の近さ。"""
        self.load()
        if not docs:
            return []
        if self.kind == "lexical":
            return [lexical_sim(query, d) for _, d in docs]
        with self.lock:
            return self._scores(query, docs)

    def _scores(self, query: str, docs: List[Tuple[str, str]]) -> List[float]:
        try:
            import numpy as np
            need = [(k, d) for k, d in docs if (k, d) not in self.cache]
            if need:
                vecs = self._encode([C.D_PREFIX + d for _, d in need])
                for (k, d), v in zip(need, vecs):
                    self.cache[(k, d)] = v
                if len(self.cache) > 5000:            # 増えすぎたら捨てる
                    self.cache = {kd: self.cache[kd] for kd in list(self.cache)[-2000:]}
            q = self._encode([C.Q_PREFIX + query])[0]
            return [float(np.dot(q, self.cache[(k, d)])) for k, d in docs]
        except Exception as e:                         # 途中で失敗したら文字の重なりで続ける
            self.kind, self.status = "lexical", f"文字の重なり（Ruri で失敗: {type(e).__name__}: {e}）"
            return [lexical_sim(query, d) for _, d in docs]
