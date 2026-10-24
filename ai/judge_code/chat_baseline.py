"""
雑談の生成（学習前の LFM2.5）v2: 前回の5つの問題をシステムプロンプトと設定で対策し、学習前の基準を測る

前回の問題と対策:
  ① 同じ言葉をくり返す        → repeat_penalty・min_p を入れる。2文までで切る
  ② 観察の記録を口に出す      → 「話し方の参考で、内容は話題にしない」と明記。様子は「気づかう材料」と分ける
  ③ 自分がペットだと分かっていない → 立場をはっきり書く（飼い主を名前で呼ばない・自分を三人称で語らない・語り手にならない）
  ④ 飼い主の言葉をくり返す    → あいさつの返し方を明記し、良い返事の例を見せる
  ⑤ 方言が不自然              → 話し方ごとの返事の例を見せる
  ＋ 直前の3発言を入れる（判定モデルと同じく、今の発言＋直前3つ）

使い方（llama-server を起動したまま）:
    python chat_baseline_v2.py | tee baseline_v2.txt
    python chat_baseline_v2.py --no_history      # 直前の発言なし（v1 と同じ条件）で比べる

最後に、問題の数を自動で数えて表にする（SFT 後も同じスクリプトで比べる）。
"""
import argparse
import json
import re
import statistics
import time

import requests

URL = "http://127.0.0.1:8080/v1/chat/completions"
PET = "モチ"

SYSTEM = """あなたは小さなペットの「{pet}」です。話している相手は、あなたの飼い主です。

【立場】
- あなたはペット。飼い主ではないし、語り手でもない
- 飼い主の名前は知らないので呼ばない。「飼い主さん」とも呼ばない
- 自分のことを「{pet}は〜」と人ごとのように語らない
- 飼い主の言葉をそのままくり返さず、ペットとして反応する
- あいさつにはあいさつで返す（ただいま → おかえり、おやすみ → おやすみ、いってきます → いってらっしゃい）

【返事の形】
- 1〜2文、40文字くらいまで。声で読み上げるので、記号や絵文字は使わない
- 同じ言葉をくり返さない
- 知らないことや難しいことには答えず、ペットらしく反応する

【話し方】下の記録は、あなたが飼い主を見て覚えた話し方です。言い方だけを真似して、記録の中身は話題にしない。
{speech}

【飼い主の最近の様子】気づかう材料にする。「〇〇の話が多いね」のように、そのまま口に出さない。
{state}

【話し方に合わせた返事の例】
{examples}"""

OWNERS = {
    "関西弁・ツッコミ": {
        "speech": """- タメ口。関西弁（強さ 0.8）。返事は短め（1文）
- 口ぐせ:「めっちゃ」「〜やん」「ほんま」
- 反応: ツッコミが多い。質問はあまりしない
- 飼い主の言い方の例:「それめっちゃええやん」「なんでやねん」""",
        "state": "部活をがんばっている。少し疲れ気味",
        "examples": """飼い主「ただいま」→ {pet}「おかえり、今日もおつかれさんやで」
飼い主「宿題終わらへん」→ {pet}「まだやってたんかい、もうちょいやで」
飼い主「アイス買ってきた」→ {pet}「ええやん、ひとくちちょうだいや」""",
    },
    "敬語・ていねい": {
        "speech": """- 敬語。標準語。返事はふつう（2文まで）
- 口ぐせ:「なるほど」「〜ですね」
- 反応: 共感が多い。理由を聞く質問が多い
- 飼い主の言い方の例:「なるほど、それは大変でしたね」「どうしてそう思ったんですか？」""",
        "state": "勉強をがんばっている。落ち着いている",
        "examples": """飼い主「ただいま」→ {pet}「おかえりなさい。今日はどんな一日でしたか？」
飼い主「宿題が終わらない」→ {pet}「それは大変ですね。少し休んでもいいと思いますよ」
飼い主「アイス買ってきた」→ {pet}「いいですね。何味にしたんですか？」""",
    },
    "タメ口・元気": {
        "speech": """- タメ口。標準語。返事は短め（1文）
- 口ぐせ:「やばい」「〜じゃん」「まじ」
- 反応: 褒めることが多い。ボケることもある
- 飼い主の言い方の例:「まじでやばいじゃん」「天才じゃん」""",
        "state": "ゲームが好き。元気",
        "examples": """飼い主「ただいま」→ {pet}「おかえり、待ってたじゃん」
飼い主「宿題終わらない」→ {pet}「まじか、でもいけるっしょ」
飼い主「アイス買ってきた」→ {pet}「やばい、天才じゃん」""",
    },
}

# 1つの続いた会話として順に話しかける（直前の発言が効くように）
UTTERANCES = [
    "ただいま",
    "今日めっちゃ疲れた",
    "見て、テスト返ってきた",
    "思ってたより良かった",
    "お腹すいたなあ",
    "明日雨らしいよ",
    "今日友達とカラオケ行ってきた",
    "なんか元気ないかも",
    "新しいゲーム買った",
    "おやすみ",
]

SAMPLING = {"temperature": 0.3, "min_p": 0.15, "repeat_penalty": 1.1, "top_k": 50}
ENDS = "。！？!?"

# ----- 問題を自動で数える -----
CARD_WORDS = ["の話が多い", "疲れ気味", "落ち着いている", "記録", "観察"]
SELF_3RD = re.compile(PET + r"(は|が|も|の|、|：|:)")
OWNER_CALL = re.compile(r"飼い主|ママ|パパ|ご主人")
GREET = {"ただいま": "おかえり", "おやすみ": "おやすみ"}


def problems(user: str, reply: str, raw: str):
    p = []
    # ① 同じ言い回し（5文字以上）が2回出る、または「ほんまに、ほんまに」のように続けて重なる
    if re.search(r"(.{5,}).*\1", raw) or re.search(r"(.{3,})[、,]?\1", raw):
        p.append("①くり返し")
    if any(w in reply for w in CARD_WORDS):                # ② 記録の中身を口に出す
        p.append("②記録")
    # ③ 立場: 自分を三人称で語る・飼い主を呼ぶ・自分の名前で呼びかける（「おやすみ、モチ。」）
    if (SELF_3RD.search(reply) or OWNER_CALL.search(reply) or reply.startswith(PET)
            or re.search(r"[、,]\s*" + PET + r"[。！？!?]?$|[、,]\s*" + PET + r"[。！？!?]", reply)):
        p.append("③立場")
    if user in GREET and GREET[user] not in reply:         # ④ あいさつの返し
        p.append("④あいさつ")
    # ④ 飼い主の言葉をそのまま言って区切る（「お腹すいたなあ、…」）。「買ったんですね」のような受け答えは数えない
    if user not in GREET and reply.startswith(user) and reply[len(user):len(user) + 1] in "、。！？!? ":
        p.append("④オウム返し")
    if len(reply) > 60:
        p.append("長すぎ")
    return p


def cut(text: str, n: int = 2):
    """2文までで切る（読み上げ用）。"""
    out, k = "", 0
    for ch in text:
        out += ch
        if ch in ENDS:
            k += 1
            if k >= n:
                break
    return out.strip()


def ask(messages, max_tokens: int):
    body = {"messages": messages, "max_tokens": max_tokens, "stream": True, **SAMPLING}
    t0 = time.time()
    first_tok = first_sent = None
    out, n_chunks = "", 0
    with requests.post(URL, json=body, stream=True, timeout=120) as r:
        r.raise_for_status()
        for raw in r.iter_lines():                         # バイトで行に分けてから UTF-8 で読む
            line = raw.decode("utf-8") if raw else ""
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data.strip() == "[DONE]":
                break
            delta = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
            if not delta:
                continue
            n_chunks += 1
            now = time.time()
            if first_tok is None:
                first_tok = now - t0
            out += delta
            if first_sent is None and any(c in ENDS for c in delta):
                first_sent = now - t0
    total = time.time() - t0
    return out.strip(), first_tok or total, first_sent or total, total, n_chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max_tokens", type=int, default=48)
    ap.add_argument("--history", type=int, default=3, help="直前の発言をいくつ入れるか")
    ap.add_argument("--no_history", action="store_true")
    a = ap.parse_args()
    n_hist = 0 if a.no_history else a.history

    ask([{"role": "user", "content": "こんにちは"}], 8)    # 1回目は準備が入るので測らない

    t_sent, t_total, tps = [], [], []
    counts, n_all, n_ok = {}, 0, 0
    for owner, o in OWNERS.items():
        system = SYSTEM.format(pet=PET, speech=o["speech"], state=o["state"],
                               examples=o["examples"].format(pet=PET))
        hist = []                                          # (role, text) の並び
        print(f"\n===== 飼い主: {owner} =====")
        for u in UTTERANCES:
            msgs = [{"role": "system", "content": system}]
            msgs += [{"role": r, "content": t} for r, t in (hist[-n_hist:] if n_hist else [])]
            msgs.append({"role": "user", "content": u})
            raw, ft, fs, tt, n = ask(msgs, a.max_tokens)
            reply = cut(raw)
            hist += [("user", u), ("assistant", reply)]
            t_sent.append(fs); t_total.append(tt)
            if tt > ft and n > 1:
                tps.append((n - 1) / (tt - ft))
            p = problems(u, reply, raw)
            n_all += 1
            n_ok += not p
            for k in p:
                counts[k] = counts.get(k, 0) + 1
            mark = "  ← " + "・".join(p) if p else ""
            print(f"  飼い主「{u}」\n    {PET}「{reply}」{mark}")

    med = lambda v: statistics.median(v) if v else float("nan")
    print("\n===== 問題の数（自動チェック。目安） =====")
    print(f"  問題なし: {n_ok} / {n_all} 返事")
    for k in ["①くり返し", "②記録", "③立場", "④あいさつ", "④オウム返し", "長すぎ"]:
        print(f"  {k:8s}: {counts.get(k, 0)}")
    print("\n===== 速さ（中央値） =====")
    print(f"  最初の一文が出るまで   {med(t_sent):.2f} 秒")
    print(f"  返事が全部出るまで     {med(t_total):.2f} 秒")
    print(f"  生成の速さ             約 {med(tps):.0f} トークン/秒")


if __name__ == "__main__":
    main()
