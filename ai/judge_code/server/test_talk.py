"""
test_talk.py — 会話サーバー（talk_server.py）にテキストを送って、返事のテキストを確かめる

流れ: テキスト → [Cloud Functions] → talk_server.py（判定モデル → LFM2.5）→ 返事のテキスト

3つの確かめ方（手前から順に）:

  ① Mac の中だけ
      python test_talk.py --key mochi2026 --text "ただいま"

  ② トンネル越し（外から届くか）
      python test_talk.py --url https://xxxx.trycloudflare.com --key mochi2026 --text "ただいま"

  ③ Cloud Functions 経由（本番と同じ道）
      python test_talk.py --cf https://asia-northeast1-pet-handoff-2aecb.cloudfunctions.net/talk \
          --api-key <FirebaseのウェブAPIキー> --email <テスト用メール> --password <パスワード> --text "ただいま"

  どれも --chat を付けると、続けて打ち込める（直前の発言はサーバーが覚えている）
      python test_talk.py --key mochi2026 --chat
"""
import argparse
import json
import sys
import time

import requests


# ---------------------------------------------------------------- 送り先ごとの呼び方
def call_server(url: str, key: str, body: dict) -> dict:
    """talk_server.py を直接呼ぶ（① と ②）。Cloud Functions がやるのと同じ形。"""
    r = requests.post(url.rstrip("/") + "/talk", json=body,
                      headers={"X-Api-Key": key} if key else {}, timeout=60)
    if r.status_code == 401:
        sys.exit("401: 合い言葉が違う（--key と、サーバー起動時の TALK_API_KEY を合わせる）")
    r.raise_for_status()
    return r.json()


def firebase_login(api_key: str, email: str, password: str) -> str:
    """Firebase Authentication にログインして ID トークンを取る（③ 用）。"""
    r = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}",
        json={"email": email, "password": password, "returnSecureToken": True}, timeout=15)
    if not r.ok:
        sys.exit(f"ログイン失敗: {r.text}")
    return r.json()["idToken"]


def call_cf(url: str, token: str, body: dict) -> dict:
    """Cloud Functions の talk（onCall）を呼ぶ（③）。onCall の決まりで data で包み、result で返る。"""
    r = requests.post(url, json={"data": body}, timeout=90,
                      headers={"Authorization": f"Bearer {token}"})
    d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
    if "error" in d or not r.ok:
        sys.exit(f"Cloud Functions のエラー（{r.status_code}）: {json.dumps(d, ensure_ascii=False)}")
    return d["result"]


# ---------------------------------------------------------------- 表示
def show(d: dict, dt: float, verbose: bool):
    print(f"  飼い主「{d.get('user_text')}」")
    print(f"  ペット「{d.get('reply_text')}」")
    print(f"    覚える言葉: {d.get('learn_words')}")
    j = d.get("judge") or {}
    t = d.get("timings_ms") or {}
    print(f"    判定: {d.get('route')}  危険 {j.get('unsafe_prob')}  気持ち {j.get('emotion')}")
    print(f"    時間: 判定 {t.get('judge')} ms / 生成 {t.get('gen')} ms / サーバー合計 {t.get('total')} ms"
          f" / 往復 {dt * 1000:.0f} ms")
    if d.get("errors"):
        print(f"    エラー: {d['errors']}")
    if verbose:
        d = dict(d)
        d.pop("audio_b64", None)
        print(json.dumps(d, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="talk_server.py の URL（① ②）")
    ap.add_argument("--key", default="", help="TALK_API_KEY（① ②）")
    ap.add_argument("--cf", help="Cloud Functions の talk の URL（③）")
    ap.add_argument("--api-key", help="Firebase のウェブAPIキー（③）")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--pet", default="demo", help="petId")
    ap.add_argument("--text", default="ただいま")
    ap.add_argument("--chat", action="store_true", help="続けて打ち込む")
    ap.add_argument("-v", "--verbose", action="store_true", help="返ってきた JSON をすべて表示")
    a = ap.parse_args()

    if a.cf:
        if not (a.api_key and a.email and a.password):
            sys.exit("--cf を使うときは --api-key・--email・--password も指定してください")
        token = firebase_login(a.api_key, a.email, a.password)
        print(f"送り先: Cloud Functions {a.cf}（ログイン済み）")
        send = lambda body: call_cf(a.cf, token, body)
    else:
        try:
            h = requests.get(a.url.rstrip("/") + "/health", timeout=10).json()
            print(f"送り先: {a.url}  health: {h}")
        except Exception as e:
            sys.exit(f"{a.url} に届かない: {e}\n  talk_server.py かトンネルが動いているか確認してください")
        send = lambda body: call_server(a.url, a.key, body)

    def once(text: str):
        body = {"petId": a.pet, "text": text, "want_audio": False}
        t0 = time.time()
        d = send(body)
        show(d, time.time() - t0, a.verbose)

    if not a.chat:
        once(a.text)
        return
    print("話しかけてください（空行で終わり）")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        once(text)


if __name__ == "__main__":
    main()