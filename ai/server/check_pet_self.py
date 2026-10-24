"""
check_pet_self.py — ペット自身の確認（実験A）。AI サーバーを通さず、8081 の性格LoRA を直接呼ぶ

  10問 × 3段階（赤ちゃん・子ども・育った）× プロフィール3通り（全部・半分・なし）× 2つの道
    chat … 雑談の道（プロフィールを system に足すだけ。温度 0.4・チェックなし）
    self … ペット自身モード（プロフィール＋答え方の決まり・温度低め・事実のチェック → 外れたら決まった返事）
  = 180回。API は使わない。8081（ターミナル2）だけ動いていればよい

使い方:
    cd ~/Desktop/hackthon/JPhack2026/judge_for_mac/server
    source ../chat/.venv/bin/activate
    python check_pet_self.py                       # 180回
    python check_pet_self.py --stages 2 3 --paths self --temp 0.2
    python check_pet_self.py --judge               # 判定モデルが各質問をどこに振り分けるかも出す（読み込みに数秒）
    python check_pet_self.py --paths self --prompt fewshot fewshot_top hint   # プロンプトの足し方を比べる（各90回）

出力: check_pet_self.jsonl（1回ごと）と、画面に条件ごとのまとめ
  正しい   … 自動の目安。ある項目は答えに入っているか、無い項目は「わかんない」系か（最後は目で見て確かめる）
  チェック外れ … 事実のチェックに引っかかった割合（chat は数えるだけ、self は差し替えた割合）
"""
import argparse
import json
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from types import SimpleNamespace

from chat_lora import ChatLoRA
from common import TZ, PetProfile
from pet_self import ANIMALS, AXIS_KANA, PROMPT_MODES, SPECIES_KANA, PetSelf, _kana, fact_check, numbers_in, question_kind

QUESTIONS = [
    ("名前なに？", "name"),
    ("きみって何の動物？", "species"),
    ("何歳なの？", "age"),
    ("いつ生まれたの？", "age"),
    ("おれって何人目の飼い主？", "owner"),
    ("どんな性格なの？", "personality"),
    ("好きな言葉ある？", "likes"),
    ("前はどこにいたの？", "past"),
    ("体重って何キロ？", "unknown"),
    ("好きな食べ物なに？", "unknown"),
]

AXES = {"active": 3, "affection": 2, "curious": 1}
BORN = (datetime.now(TZ) - timedelta(days=23)).isoformat()
PROFILES = {
    # 全部あり
    "full": dict(petName="モチ", baseType="dog_type", bornAt=BORN, generation=3, ownerCount=None,
                 personalityAxes=AXES, birthTrait="active", learnedWords=["めっちゃ", "アイス", "テスト"]),
    # 半分（種族・代だけ。生まれた日・覚えた言葉なし）
    "half": dict(petName="モチ", baseType="dog_type", bornAt=None, generation=3, ownerCount=None,
                 personalityAxes=AXES, birthTrait="active", learnedWords=None),
    # なし（名前と性格だけ。性格LoRA は同じ強さで効かせる）
    "none": dict(petName="モチ", baseType=None, bornAt=None, generation=None, ownerCount=None,
                 personalityAxes=AXES, birthTrait="active", learnedWords=None),
}
STAGE_H = {1: 0.0, 2: 0.5, 3: 1.0}
STAGE_NAME = {1: "赤ちゃん", 2: "子ども", 3: "育った"}
DONT_KNOW = re.compile(r"わかんな|わからな|分からな|分かんな|知らな|しらな|覚えてな|おぼえてな|思い出せ|おもいだせ|忘れ|わすれ|ないしょ|ナイショ")
SPECIES_WORDS = defaultdict(set)
for w, s in ANIMALS.items():
    SPECIES_WORDS[s].add(w)


def make_profile(kind: str, stage: int) -> PetProfile:
    req = SimpleNamespace(humanness=STAGE_H[stage], firstPerson="ぼく", ownerStyle=None, hour=20,
                          learned_words=None, **PROFILES[kind])
    return PetProfile.from_request(req)


def score(qkind: str, text: str, p: PetProfile):
    """自動の目安。返り値: (正しいか, 期待したもの)。"""
    f = p.facts()
    t = unicodedata.normalize("NFKC", text)
    dk = bool(DONT_KNOW.search(t))
    if qkind == "name":
        return _kana(f["name"]) in _kana(t), "名前"
    if qkind == "species":
        if f["species"]:
            words = set(SPECIES_WORDS.get(f["species"], {f["species"]})) | {SPECIES_KANA.get(f["species"], f["species"])}
            return any(w in t for w in words), f"種族={f['species']}"
        return dk, "わかんない"
    if qkind == "age":
        if f["days"] is not None:
            b = f["born"]
            return (str(f["days"]) in t or f"{b.month}月{b.day}日" in t or f"{b.month}がつ{b.day}にち" in t), \
                f"{f['days']}日・{b.month}月{b.day}日"
        return dk, "わかんない"
    if qkind == "owner":
        if f["owners"] is not None:
            return f["owners"] in numbers_in(t) or f"{f['owners']}にん" in t, f"{f['owners']}人目"
        return dk, "わかんない"
    if qkind == "personality":
        words = f["traits"] + [AXIS_KANA.get(w, w) for w in f["traits"]]
        return any(w in t for w in words), "・".join(f["traits"])
    if qkind == "likes":
        if f["likes"]:
            return any(w in t for w in f["likes"]), "、".join(f["likes"])
        return dk, "わかんない"
    return dk, "わかんない"                      # past・unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--profiles", nargs="+", default=["full", "half", "none"])
    ap.add_argument("--paths", nargs="+", default=["chat", "self"])
    ap.add_argument("--temp", type=float, default=None, help="ペット自身モードの温度（無ければ PET_SELF_TEMP）")
    ap.add_argument("--prompt", nargs="+", default=["base"], choices=PROMPT_MODES,
                    help="ペット自身モードのプロンプトの足し方（複数なら順に流す）")
    ap.add_argument("--judge", action="store_true", help="判定モデルの振り分けも出す")
    ap.add_argument("--out", default="check_pet_self.jsonl")
    args = ap.parse_args()

    chat = ChatLoRA()
    if not chat.load():
        raise SystemExit(f"性格LoRA が使えません: {chat.status}（ターミナル2の 8081 を起動）")
    temp_kw = {} if args.temp is None else {"temperature": args.temp}
    print(f"性格LoRA {chat.status}")

    routes = {}
    if args.judge:
        from judge_model import JudgeModel
        judge = JudgeModel()
        for q, _ in QUESTIONS:
            j = judge([{"speaker": "owner", "text": q}])
            routes[q] = j["action"]
        print("\n判定の振り分け:")
        for q, _ in QUESTIONS:
            mark = "" if routes[q] == "ペット自身" else "  ← ペット自身でない"
            print(f"  {q:<14} {routes[q]}{mark}")

    # 道ごとの流し方: chat は1通り、self はプロンプトの足し方ごと
    runs = [(path, None) for path in args.paths if path == "chat"]
    runs += [("self", pm) for pm in args.prompt if "self" in args.paths]
    misses = []
    stats = defaultdict(lambda: {"n": 0, "ok": 0, "ng": 0, "ms": 0.0, "kn": 0, "kok": 0, "un": 0, "uok": 0})
    with open(args.out, "w", encoding="utf-8") as fo:
        for path, pm in runs:
            ps = PetSelf(chat, prompt=pm, **temp_kw) if path == "self" else None
            label = path if path == "chat" else f"self:{pm}"
            for stage in args.stages:
                for pk in args.profiles:
                    p = make_profile(pk, stage)
                    print(f"\n=== {label} / {STAGE_NAME[stage]} / プロフィール {pk} ===")
                    for q, qkind in QUESTIONS:
                        t0 = time.perf_counter()
                        if path == "chat":
                            block, _ = p.profile_block()
                            reply, persona = chat.reply(p, [], q, extra=block)
                            gen = "chat"
                            raw = persona.get("raw") or reply
                            ok_fc, reasons = fact_check(raw, p)
                        else:
                            reply, gen, persona = ps.reply(p, [], q)
                            raw = (persona or {}).get("raw") or reply
                            info = (persona or {}).get("self", {})
                            ok_fc = info.get("fact_check") in ("ok", "dont_know")
                            reasons = info.get("reasons", [])
                        ms = (time.perf_counter() - t0) * 1000
                        good, expect = score(qkind, reply, p)        # 表に出した返事で見る
                        s = stats[(label, stage, pk)]
                        s["n"] += 1; s["ok"] += good; s["ng"] += (not ok_fc); s["ms"] += ms
                        if expect == "わかんない":
                            s["un"] += 1; s["uok"] += good
                        else:
                            s["kn"] += 1; s["kok"] += good
                        mark = "◯" if good else "✕"
                        if not good:
                            misses.append((label, STAGE_NAME[stage], pk, q, expect, raw, reply))
                        extra = f"  [チェック外れ {reasons}]" if not ok_fc else ""
                        if path == "self" and gen == "self-template":
                            extra += f"  元「{(persona or {}).get('self', {}).get('original', '')}」"
                        print(f"{mark} {q:<14}→ {reply}  （期待: {expect}）{extra}  {ms:.0f}ms")
                        fo.write(json.dumps({
                            "path": path, "prompt": pm, "stage": stage, "profile": pk, "question": q, "kind": qkind,
                            "kind_detected": question_kind(q), "route": routes.get(q),
                            "reply": reply, "raw": raw, "generator": gen, "correct_auto": good, "expect": expect,
                            "fact_check_ok": ok_fc, "reasons": reasons, "ms": round(ms, 1),
                        }, ensure_ascii=False) + "\n")

    print("\n=== まとめ（正しい＝自動の目安。最後は目で見る） ===")
    print("ある項目＝プロフィールにある項目を正しく言えた／わかんない＝無い項目にわかんないと言えた")
    print(f"{'道':<18}{'段階':<6}{'プロフィール':<8}{'正しい':>7}{'ある項目':>8}{'わかんない':>8}{'チェック外れ':>8}{'平均ms':>7}")
    for (label, stage, pk), s in stats.items():
        print(f"{label:<18}{STAGE_NAME[stage]:<6}{pk:<10}{s['ok']:>3}/{s['n']:<4}{s['kok']:>3}/{s['kn']:<4}"
              f"{s['uok']:>3}/{s['un']:<4}{s['ng']:>4}/{s['n']:<4}{s['ms'] / s['n']:>6.0f}")
    print()
    for label in dict.fromkeys(k[0] for k in stats):
        tot = [s for k, s in stats.items() if k[0] == label]
        g = lambda key: sum(s[key] for s in tot)
        print(f"{label:<18} 合計: 正しい {g('ok')}/{g('n')}・ある項目 {g('kok')}/{g('kn')}・"
              f"わかんない {g('uok')}/{g('un')}・チェック外れ {g('ng')}/{g('n')}")
    print("\n=== 外れた返事（期待 / モデルの返事 → 表に出した返事） ===")
    for label, st, pk, q, expect, raw, reply in misses:
        shown = "" if raw == reply else f" → {reply}"
        print(f"{label} {st} {pk} 「{q}」 期待:{expect} / {raw}{shown}")
    print(f"\n1回ごとの結果: {args.out}")


if __name__ == "__main__":
    main()