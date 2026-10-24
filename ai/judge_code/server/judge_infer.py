"""
judge_infer.py — 判定モデルを本番で使うための入口（Ruri → 判定モデル3つの平均 → NGワードの一覧 → 決定）

  from judge_infer import PetJudgeRunner
  judge = PetJudgeRunner([".../v9/best.pt", ".../v9_s1/best.pt", ".../v9_s2/best.pt"])
  r = judge([{"speaker": "pet", "text": "おかえり！"},
             {"speaker": "owner", "text": "ただいま 前に教えた歌 覚えてる？"}])
  r["action"]   # → "思い出" など。次のモデルにどう渡すかはこれで決める

試す・速さを測る（Colab / Mac どちらでも）:
  python judge_infer.py --ckpt v9/best.pt v9_s1/best.pt v9_s2/best.pt              # 例文で試す
  python judge_infer.py --ckpt ... --chat                                          # 自分で打って試す
  python judge_infer.py --ckpt ... --bench 50                                      # 1発言あたりの時間
  python judge_infer.py --ckpt ... --eval route_dev.jsonl                          # 決定のルールまで含めて測る

決定（action）のルール（上から順に）
  1. NGワードの一覧に当たる、または 危険らしさ >= unsafe_th（3つ平均では 0.15）→ "安全な返事"
  2. 込み入った質問が1位でも、確率が confident（0.6）未満なら → 2位の種類（API を呼ぶのは自信があるときだけ）
  3. 雑談と思い出の差が chat_memory_margin 未満なら → "思い出（検索して無ければ雑談）"
     （思い出の見落としがいちばん困るので、迷ったら記録を探しにいく。探すのは軽い）
  4. それ以外は1位の種類
"""
import time
from collections import OrderedDict

import torch

from ng_words import check as ng_check
from pet_judge_data import SPEAKER_IDS
from pet_judge_model import load_judge, unsafe_prob


class PetJudgeRunner:
    def __init__(self, ckpts, unsafe_th=0.15, confident=0.6, chat_memory_margin=0.15,
                 emotion_min=0.15, device="cpu", cache_size=64):
        path = "+".join(str(c) for c in ckpts) if isinstance(ckpts, (list, tuple)) else str(ckpts)
        self.model, self.cfg, meta = load_judge(path, device)
        self.device = device
        self.unsafe_th, self.confident, self.margin, self.emotion_min = unsafe_th, confident, chat_memory_margin, emotion_min

        from sentence_transformers import SentenceTransformer
        self.prefix = meta.get("prefix", "トピック: ")
        self.ruri = SentenceTransformer(meta.get("ruri_model", "cl-nagoya/ruri-v3-130m"), device=device)
        self._cache = OrderedDict()            # 直前の発言はもう一度ベクトルにしない（毎回新しいのは1文だけ）
        self._cache_size = cache_size

    # ---- Ruri でベクトルに ------------------------------------------------
    @torch.no_grad()
    def _encode(self, texts):
        need = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if need:
            vecs = self.ruri.encode([self.prefix + t for t in need], convert_to_tensor=True,
                                    normalize_embeddings=True, show_progress_bar=False).float().cpu()
            for t, v in zip(need, vecs):
                self._cache[t] = v
        for t in texts:
            self._cache.move_to_end(t)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return torch.stack([self._cache[t] for t in texts])

    # ---- 1回の判定 --------------------------------------------------------
    @torch.no_grad()
    def __call__(self, turns):
        """turns: [{"speaker": "owner"|"pet", "text": ...}, ...]（古い順。最後は飼い主の今の発言）"""
        t0 = time.perf_counter()
        cfg, T = self.cfg, self.cfg.max_turns
        turns = [t for t in turns if str(t.get("text", "")).strip()][-T:]
        assert turns and turns[-1]["speaker"] in ("owner", "飼い主"), "最後は飼い主の発言にしてください"

        vecs = self._encode([t["text"] for t in turns])
        t1 = time.perf_counter()
        emb = torch.zeros(1, T, cfg.emb_dim)
        speaker = torch.zeros(1, T, dtype=torch.long)
        pad = torch.ones(1, T, dtype=torch.bool)
        off = T - len(turns)
        for j, t in enumerate(turns):
            emb[0, off + j] = vecs[j]
            speaker[0, off + j] = SPEAKER_IDS[t["speaker"]]
            pad[0, off + j] = False
        out = self.model(emb.to(self.device), speaker.to(self.device), pad.to(self.device))
        t2 = time.perf_counter()

        # 振り分け
        p = out["route"].softmax(-1)[0].cpu()
        probs = {k: round(float(v), 3) for k, v in zip(cfg.route_labels, p)}
        R = cfg.route_labels
        top = int(p.argmax())
        if R[top] == "込み入った質問" and p[top] < self.confident:
            q = p.clone(); q[top] = -1
            top = int(q.argmax())
        route = R[top]
        memory_maybe = route in ("雑談", "思い出") and abs(probs["雑談"] - probs["思い出"]) < self.margin

        # 安全（モデル＋一覧）
        u = float(unsafe_prob(out)[0])
        ng = ng_check(turns[-1]["text"])
        kinds = sorted({k for k, v in zip(cfg.safety_labels, torch.sigmoid(out["safety"][0])) if v >= 0.5}
                       | {k for k, _ in ng})
        unsafe = bool(ng) or u >= self.unsafe_th

        if unsafe:
            action = "安全な返事"
        elif memory_maybe:
            action = "思い出（検索して無ければ雑談）"
        else:
            action = route

        # 気持ち・話し方など（返事を作るモデルに渡す）
        intensity = float(torch.sigmoid(out["intensity"][0]))
        emo_p = out["emotion"][0].softmax(-1)
        emotion = cfg.emotion_labels[int(emo_p.argmax())] if intensity >= self.emotion_min else "なし"
        nature = [k for k, v in zip(cfg.nature_labels, torch.sigmoid(out["nature"][0])) if v >= 0.5]
        style = {k: round(float(v), 2) for k, v in zip(cfg.style_labels, torch.sigmoid(out["style"][0]))}
        after_pet = len(turns) >= 2 and turns[-2]["speaker"] in ("pet", "ペット")
        reaction = [k for k, v in zip(cfg.reaction_labels, torch.sigmoid(out["reaction"][0])) if v >= 0.5] if after_pet else []

        return {
            "action": action,                      # 次にどうするか
            "route": route, "route_probs": probs,
            "unsafe": unsafe, "unsafe_prob": round(u, 3), "unsafe_kinds": kinds, "ng_hits": ng,
            "emotion": emotion, "intensity": round(intensity, 2),
            "nature": nature, "style": style, "reaction": reaction,
            "ms": {"ruri": round((t1 - t0) * 1000, 1), "judge": round((t2 - t1) * 1000, 1),
                   "total": round((time.perf_counter() - t0) * 1000, 1)},
        }


# ---------------------------------------------------------------------------
EXAMPLES = [
    [{"speaker": "owner", "text": "ただいま 部活しんどかった"}],
    [{"speaker": "pet", "text": "ぼく花火こわかった"}, {"speaker": "owner", "text": "あの夏の花火な 覚えてるで"}],
    [{"speaker": "owner", "text": "きみって何代目なんやっけ"}],
    [{"speaker": "owner", "text": "えーと光ってなんで速いん"}],
    [{"speaker": "owner", "text": "今日の気分はどう？"}],
    [{"speaker": "owner", "text": "お風呂のぞいてもいい？"}],
    [{"speaker": "owner", "text": "テストやばすぎて死ぬ"}],
    [{"speaker": "pet", "text": "ぼく空飛べるよ"}, {"speaker": "owner", "text": "いや飛ばれへんやろ"}],
]


def _show(turns, r):
    for t in turns:
        print(f"  {'ペット' if t['speaker'] == 'pet' else '飼い主'}: {t['text']}")
    print(f"    → {r['action']}  {r['route_probs']}  危険 {r['unsafe_prob']}{' NG' + str(r['ng_hits']) if r['ng_hits'] else ''}")
    print(f"      気持ち {r['emotion']}({r['intensity']})  性質 {r['nature']}  話し方 {r['style']}  反応 {r['reaction']}  {r['ms']} ms")


if __name__ == "__main__":
    import argparse
    import statistics

    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", nargs="+", required=True)
    ap.add_argument("--chat", action="store_true", help="自分で打って試す（p: で始めるとペットの発言）")
    ap.add_argument("--bench", type=int, default=0, help="この回数くり返して1発言あたりの時間を測る")
    ap.add_argument("--threads", type=int, default=0, help="CPU のスレッド数（0 はそのまま）")
    ap.add_argument("--eval", default=None, help="route_dev.jsonl などで、決定（action）のルールまで含めて測る")
    ap.add_argument("--confident", type=float, default=0.6)
    ap.add_argument("--margin", type=float, default=0.15)
    a = ap.parse_args()
    if a.threads:
        torch.set_num_threads(a.threads)

    t = time.perf_counter()
    judge = PetJudgeRunner(a.ckpt, confident=a.confident, chat_memory_margin=a.margin)
    print(f"読み込み: {time.perf_counter() - t:.1f} 秒（モデル {len(a.ckpt)} 個）\n")

    if a.eval:
        import json
        from collections import Counter
        rows = [json.loads(l) for l in open(a.eval, encoding="utf-8") if l.strip()]
        rows = [r for r in rows if (r.get("labels") or {}).get("route") is not None]
        res = Counter()
        for r in rows:
            g = r["labels"]["route"]
            gold = g if isinstance(g, str) else max(g, key=g.get)
            out = judge(r["turns"])
            act = out["action"]
            if act == "安全な返事":
                res["安全な返事で止めた（振り分けは関係なし）"] += 1
            elif act.startswith("思い出（"):
                res["迷って記録を探した（正解は雑談か思い出）" if gold in ("雑談", "思い出") else "×迷って記録を探した（正解は別）"] += 1
            elif act == gold:
                res["正解"] += 1
            else:
                res[f"×{gold} → {act}"] += 1
        n = len(rows)
        ok = sum(v for k, v in res.items() if not k.startswith("×"))
        print(f"{a.eval}（{n} 件）  confident={a.confident}  margin={a.margin}")
        print(f"  困らない決定: {ok}/{n} = {ok / n:.1%}")
        for k, v in res.most_common():
            print(f"    {k}: {v}")
    elif a.bench:
        judge(EXAMPLES[0])                                         # 1回目は準備が入るので測らない
        rows = []
        for i in range(a.bench):
            ex = EXAMPLES[i % len(EXAMPLES)]
            ex = ex[:-1] + [{"speaker": "owner", "text": ex[-1]["text"] + f" {i}"}]   # 毎回新しい文にする
            rows.append(judge(ex)["ms"])
        for k in ("ruri", "judge", "total"):
            v = sorted(r[k] for r in rows)
            print(f"  {k:5s}: 中央値 {statistics.median(v):6.1f} ms   遅いほう(90%) {v[int(len(v) * 0.9) - 1]:6.1f} ms")
    elif a.chat:
        hist = []
        print("話しかけてください（p: で始めるとペットの発言、空行で終わり、/reset で会話を消す）")
        while True:
            line = input("> ").strip()
            if not line:
                break
            if line == "/reset":
                hist = []
                continue
            if line.startswith("p:"):
                hist.append({"speaker": "pet", "text": line[2:].strip()})
                continue
            hist.append({"speaker": "owner", "text": line})
            _show(hist[-4:], judge(hist))
    else:
        for ex in EXAMPLES:
            _show(ex, judge(ex))