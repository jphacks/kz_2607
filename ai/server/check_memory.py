"""
check_memory.py — 思い出の返事の確認用（19問 × 3段階 × 材料3通り = 171回）

偽の memories・nameMap・journeys・pastMemories をここに書いておき、バックエンドを待たずに確かめる。
日付は「今日」から数えて作るので、「昨日」「先週」のしぼり込みもいつ動かしても同じに試せる。

    cd kz_2607/ai/server
    # 1. 近さだけ見る（8081 いらない）→ MEMORY_MIN_SIM を決める
    python check_memory.py --scores-only
    python check_memory.py --scores-only --ruri judge     # 判定モデルの Ruri を使い回したとき（起動が遅い）
    # 2. 返事まで（8081 の性格LoRA が必要）
    python check_memory.py
    python check_memory.py --stage 3 --material all --min-sim 0.8

材料
    all     … memories・nameMap・journeys（2代分）あり。今は3代目
    current … memories・nameMap だけ。今は1代目（前の代の質問は「最初からここにいる」）
    none    … どれも無し。今は1代目
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

from common import TZ, PetProfile
from check_memory_data import QUESTIONS, build_data, expected_ok, key_ok, material


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores-only", action="store_true", help="近さと選ばれたものだけ（8081 いらない）")
    ap.add_argument("--stage", type=int, nargs="*", default=[1, 2, 3])
    ap.add_argument("--material", nargs="*", default=["all", "current", "none"])
    ap.add_argument("--ruri", default=os.environ.get("MEMORY_RURI", "auto"), help="auto・judge・own・lexical")
    ap.add_argument("--min-sim", type=float, default=None, help="MEMORY_MIN_SIM を上書き")
    ap.add_argument("--min-lift", type=float, default=None, help="MEMORY_MIN_LIFT を上書き")
    ap.add_argument("--out", default="check_memory_result.jsonl")
    args = ap.parse_args()
    if args.min_sim is not None:
        os.environ["MEMORY_MIN_SIM"] = str(args.min_sim)

    import mem_config as C        # 環境変数を変えてから読む
    import memory as MEM
    if args.min_sim is not None:
        C.MEMORY_MIN_SIM = args.min_sim
    if args.min_lift is not None:
        C.MEMORY_MIN_LIFT = args.min_lift
    emb = MEM.Embedder(mode=args.ruri)
    if args.ruri in ("auto", "judge"):
        try:
            from judge_model import JudgeModel
            t0 = time.time()
            emb.attach(JudgeModel().runner)
            print(f"[ruri] 判定モデル読み込み {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[ruri] 判定モデルを読めない: {e}")
    emb.load()
    print(f"[ruri] {emb.status}  下限 {emb.min_sim}・ふだんとの差の下限 {C.MEMORY_MIN_LIFT}"
          f"・2件目は1位との差 {C.MEMORY_SECOND_GAP} まで")

    today = datetime.now(TZ).date()
    memories, name_map, journeys, past_memories = build_data(today)

    if args.scores_only:
        items = MEM.parse_memories(memories, MEM.norm_name_map(name_map))
        n_ok = 0
        for q, exp, key in QUESTIONS:
            kind = MEM.memory_kind(q)
            if kind == "current":
                picked, info = MEM.select_memories(emb, q, items, MEM.norm_name_map(name_map), today)
                info["kind"] = kind
                info["lines"] = [m["text"] for m in picked]
                # 全件の近さ（日付でしぼる前）も見る
                allsim = emb.scores(q, [(m["id"], m["text"]) for m in items])
                rank = sorted(zip([m["id"] for m in items], allsim), key=lambda x: -x[1])
                ok = expected_ok(exp, "all", info)
                n_ok += ok
                print(f"{'○' if ok else '×'} {q}  期待{exp}  選んだ{info.get('picked')}  日付{info.get('date')}"
                      f"  {info.get('why') or ''}")
                print("     全件: " + "  ".join(f"{i}:{s:.3f}" for i, s in rank[:5]))
                med = sorted(allsim)[len(allsim) // 2]
                print(f"     1位 {rank[0][1]:.3f}・中央値 {med:.3f}・ふだんとの差 {rank[0][1] - med:.3f}"
                      + (f"・1位と2位の差 {rank[0][1] - rank[1][1]:.3f}" if len(rank) >= 2 else ""))
            else:
                p = PetProfile(generation=3)
                lines, info, _ = MEM.MemoryTalk(None, emb).materials(kind, p, q, memories, MEM.norm_name_map(name_map),
                                                                     journeys, today, past_memories)
                says = info.get("_says") or []
                first = (info.get("keys") or [None])[0]
                ok = exp is not None and bool(lines) and f"g{info.get('generation')}" in exp and key_ok(key, info)
                n_ok += ok
                print(f"{'○' if ok else '×'} {q}  種類{kind}  期待{exp}/{key}  選んだ代 {info.get('generation')}"
                      f"  質問{info.get('question')}  先頭{first} {info.get('picked') or ''}  「{says[0] if says else ''}」"
                      f"  前の代の思い出 {info.get('past_n')}件（外した {info.get('past_dropped')}） 近さ{info.get('past_scores')}")
        print(f"\n期待どおり {n_ok}/{len(QUESTIONS)}（材料 all）")
        return

    from chat_lora import ChatLoRA
    chat = ChatLoRA()
    chat.load()
    print(f"[chat] {chat.status}")
    mt = MEM.MemoryTalk(chat, emb)
    rows, stats = [], {}
    for mat in args.material:
        mems, nm, js, pms, gen = material(mat, memories, name_map, journeys, past_memories)
        for st in args.stage:
            p = PetProfile(name="モチ", axes={"talkative": 0.6, "affection": 0.4, "active": 0.2}, stage=st,
                           generation=gen, hour=20, first_person="ぼく")
            for q, exp, key in QUESTIONS:
                t0 = time.perf_counter()
                reply, gen_name, persona = mt.reply(p, [], q, mems, nm, js, today=today, past_memories=pms)
                ms = (time.perf_counter() - t0) * 1000
                info = persona.get("memory", {})
                ok = expected_ok(exp, mat, info, key)
                s = stats.setdefault((mat, st), {"n": 0, "pick_ok": 0, "model_ok": 0, "replaced": 0})
                s["n"] += 1
                s["pick_ok"] += ok
                s["model_ok"] += info.get("check") in ("ok", "react-ok")
                s["replaced"] += info.get("check") in ("replaced", "react-dropped")
                print(f"[{mat}/段階{st}] {'○' if ok else '×'} {q} → 「{reply}」 {gen_name} {info.get('check')}"
                      + (f" {info.get('reasons')} 元「{info.get('original') or info.get('reaction_raw')}」"
                         if info.get("check") in ("replaced", "react-dropped") else "")
                      + f" {ms:.0f}ms")
                rows.append({"material": mat, "stage": st, "q": q, "expected": exp, "reply": reply,
                             "generator": gen_name, "memory": info, "raw": persona.get("raw"), "ms": round(ms)})
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print("\n材料/段階  選び方○  モデルの一言ok  一言を外した・差し替え")
    for (mat, st), s in stats.items():
        print(f"{mat:8s}/{st}   {s['pick_ok']}/{s['n']}     {s['model_ok']}          {s['replaced']}")
    print(f"→ {args.out}")


if __name__ == "__main__":
    sys.exit(main())