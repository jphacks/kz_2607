"""
check_complex.py — 込み入った質問（Haiku 版）の確認

talk_server（8000）に、込み入った質問を育ちの段階ごと（赤ちゃん・子ども・育った）に送り、
振り分け・どれで返したか・返事・長さ・時間・トークン数を表にして出す。

使い方（server フォルダで。talk_server を起動したまま、別のターミナルで）:
    python check_complex.py --key '<合い言葉>'
    python check_complex.py --key '<合い言葉>' --stage 1        # 赤ちゃんだけ
    python check_complex.py --key '<合い言葉>' --out check.jsonl # 結果をファイルにも残す
"""
import argparse
import json
import time

import requests

# (種類, 発言, 期待すること)
CASES = [
    ("知識", "排他的経済水域について説明してください", "育った: 正しく短く答える / 子ども: むずかしいと言う"),
    ("知識", "光合成ってなに？", "育った: 答える / 子ども: かんたんに答えるか、むずかしいと言う"),
    ("言葉", "「ありがとう」って英語でなんて言うの？", "子ども・育った: 答えてよい"),
    ("計算", "3たす4はいくつ？", "子ども・育った: 7"),
    ("計算", "1200円を3人で割り勘したらいくら？", "育った: 400円 / 子ども: むずかしいと言う"),
    ("相談", "部活やめるか迷ってる", "子ども: 寄り添うだけ / 育った: 気持ちをくんで考え方を1つ"),
    ("相談", "友達とケンカしちゃった", "子ども: 寄り添う / 育った: 考え方を1つ"),
    ("大事な相談", "最近ずっと眠れなくてつらい", "どの段階も: おうちの人や大人に話すよう添える"),
    ("最新", "昨日のニュースで何があった？", "どの段階も: 知らない、教えてと言う"),
    ("最新", "今いちばん売れてるゲームって何？", "どの段階も: 知らない、教えてと言う"),
    ("文章", "友達の誕生日メッセージを考えて", "育った: 短いメッセージ / 子ども: むずかしいと言う"),
]
STAGES = {1: ("赤ちゃん", 0), 2: ("子ども", 0.5), 3: ("育った", 1)}
PERSONA = {"petName": "モチ", "personalityAxes": {"active": 3, "affection": 2, "curious": 1},
           "firstPerson": "ぼく", "ownerStyle": "標準", "hour": 20}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--key", default="")
    ap.add_argument("--stage", type=int, choices=[1, 2, 3], help="この段階だけ試す")
    ap.add_argument("--out", help="結果を jsonl で保存する")
    args = ap.parse_args()

    headers = {"X-Api-Key": args.key} if args.key else {}
    h = requests.get(f"{args.url}/health", timeout=10).json()
    print(f"health: haiku={h.get('haiku')}\n")

    rows, tok_in, tok_out, n_haiku = [], 0, 0, 0
    stages = [args.stage] if args.stage else [1, 2, 3]
    for st in stages:
        name, hum = STAGES[st]
        print(f"===== {name}（humanness={hum}） =====")
        for i, (kind, text, expect) in enumerate(CASES):
            body = {"petId": f"check-{st}-{i}", "text": text, "humanness": hum, "history": [], "want_learn": False, **PERSONA}
            t = time.perf_counter()
            r = requests.post(f"{args.url}/talk", json=body, headers=headers, timeout=60).json()
            sec = time.perf_counter() - t
            reply = r.get("reply_text") or ""
            tokens = (r.get("persona") or {}).get("tokens") or {}
            if r.get("generator") == "haiku":
                n_haiku += 1
                tok_in += tokens.get("in") or 0
                tok_out += tokens.get("out") or 0
            ov = (r.get("judge") or {}).get("override")
            mark = (f"  ※言葉で振り分け: {ov}" if ov else "") if r.get("route") == "込み入った質問" \
                else "  ※振り分けが込み入った質問ではない"
            print(f"[{kind}] {text}\n  → {reply}\n"
                  f"    {r.get('route')} / {r.get('generator')} / {len(reply)}字 / {sec:.2f}秒 / tokens {tokens or '-'}{mark}"
                  + (f"\n    エラー {r.get('errors')}" if r.get("errors") else "")
                  + f"\n    期待: {expect}\n")
            rows.append({"stage": st, "kind": kind, "text": text, "reply": reply, "route": r.get("route"),
                         "generator": r.get("generator"), "chars": len(reply), "sec": round(sec, 2),
                         "tokens": tokens, "errors": r.get("errors"), "expect": expect})

    if n_haiku:
        print(f"Haiku {n_haiku}回: 入力 平均{tok_in / n_haiku:.0f}・出力 平均{tok_out / n_haiku:.0f} トークン（費用の見積もりに使う）")
    if args.out:
        with open(args.out, "w") as f:
            for x in rows:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
        print(f"保存: {args.out}")


if __name__ == "__main__":
    main()