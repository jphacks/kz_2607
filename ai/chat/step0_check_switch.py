"""
Step 0-3: llama-server でLoRAの強さを依頼ごとに変えられるかを確かめる

使い方（step0_mac_server.sh でサーバーを起動した状態で、別のターミナルから）:
    pip install requests
    python step0_check_switch.py

合格の目安:
    - 強さ 0.0 では「ワン」がほぼ出ない
    - 強さ 1.0 では「ワン」がほぼ毎回出る
    - 強さ 0.5 はその中間（割合で効き方が変わる＝性格の割合で混ぜられる）
    - 同じ時間に違う強さの依頼を送っても、互いに混ざらない
あわせて、生成速度（トークン/秒）を記録する。
"""
import concurrent.futures as cf
import time

import requests

URL = "http://127.0.0.1:8080"
PROMPTS = ["今日はいい天気だね", "おかえり", "何して遊ぶ？", "眠くない？", "今日は雨だった"]
SEEDS = range(4)


def ask(prompt: str, scale: float, seed: int = 0):
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 48,
        "temperature": 0.7,
        "seed": seed,
        # 読み込んだ順に id 0, 1, ...。書かなかったLoRAは強さ0になる
        "lora": [{"id": 0, "scale": scale}],
    }
    t0 = time.time()
    r = requests.post(f"{URL}/v1/chat/completions", json=body, timeout=120)
    r.raise_for_status()
    js = r.json()
    text = js["choices"][0]["message"]["content"]
    n_tok = js.get("usage", {}).get("completion_tokens", 0)
    return text, n_tok, time.time() - t0


def has_wan(text: str) -> bool:
    return "ワン" in text


def main():
    print("読み込まれているLoRA:", requests.get(f"{URL}/lora-adapters", timeout=10).json())
    print()

    # 1) 強さを変えたときの効き方
    print("=== 1. 強さごとの効き方 ===")
    for scale in (0.0, 0.5, 1.0):
        hits, tok_total, sec_total, n = 0, 0, 0.0, 0
        example = None
        for p in PROMPTS:
            for seed in SEEDS:
                text, n_tok, sec = ask(p, scale, seed)
                hits += has_wan(text)
                tok_total += n_tok
                sec_total += sec
                n += 1
                if example is None:
                    example = f"{p} → {text.strip()}"
        tps = tok_total / sec_total if sec_total else 0
        print(f"強さ {scale:.1f}: 「ワン」 {hits}/{n}  速度 {tps:.0f} トークン/秒")
        print(f"  例: {example}")
    print()

    # 2) 強さ0と強さ1を同時に送って、混ざらないか
    print("=== 2. 同時に送ったとき（強さ0 と 強さ1） ===")
    leak_0, miss_1, n = 0, 0, 0
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        for p in PROMPTS:
            for seed in SEEDS:
                f0 = ex.submit(ask, p, 0.0, seed)
                f1 = ex.submit(ask, p, 1.0, seed)
                t0, _, _ = f0.result()
                t1, _, _ = f1.result()
                leak_0 += has_wan(t0)
                miss_1 += not has_wan(t1)
                n += 1
                if n <= 2:
                    print(f"  {p}\n    強さ0: {t0.strip()}\n    強さ1: {t1.strip()}")
    print(f"強さ0 なのに「ワン」: {leak_0}/{n}（0 に近いほどよい）")
    print(f"強さ1 なのに「ワン」なし: {miss_1}/{n}（0 に近いほどよい）")
    print()
    print("この出力をそのまま貼ってください。")


if __name__ == "__main__":
    main()
