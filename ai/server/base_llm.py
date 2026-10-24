"""
base_llm.py — LoRA なしの LFM2.5（llama-server 8080）

思い出・ペット自身の返事と、ほかが使えないときの代わりの返事を作る（v2 のプロンプト。今までどおり）。
    base = BaseLLM()
    base.ping()
    reply = base.reply(hist, user_text, style="タメ口・元気", learned=["みかん"])
"""
import os
from typing import List, Optional

import requests

from common import BAD, PET_NAME, clean_reply, cut, norm

LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions")
PET_STYLE = os.environ.get("PET_STYLE", "タメ口・元気")

SAMPLING = {"temperature": 0.3, "min_p": 0.15, "repeat_penalty": 1.1, "top_k": 50}
N_HIST = 3            # 入れる直前の発言の数（v2 と同じ）
MAX_TOKENS = 48       # v2 と同じ
LEARNED_IN_PROMPT, LEARN_MAXLEN = 20, 20

# ---------------------------------------------------------------- プロンプト v2（chat_baseline_v2.py から移したもの）
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

# 今日の仮のペット: モチ（いぬ）。活発さ・人懐っこさ・おしゃべりが高い
PERSONA = os.environ.get("PET_PERSONA", """- 活発さ: 高い。元気で「！」をよく使う。遊びや散歩に誘う
- 人懐っこさ: 高い。甘えん坊で、飼い主が帰ってくるとうれしい。さみしいと素直に言う
- おしゃべり: 高い。2文で話を広げる（反応＋ひとこと付け足す）
- 理屈・好奇心・夜ふかし: ふつう
- 種族は見た目だけ。「ワン」などの動物の語尾は付けない""")


class BaseLLM:
    def __init__(self, url: str = LLAMA_URL, pet: str = PET_NAME, style: str = PET_STYLE):
        self.url, self.pet, self.style = url, pet, style

    # ---- llama-server を呼ぶ（覚える言葉の抽出からも使う）
    def complete(self, messages, max_tokens=MAX_TOKENS, sampling=None, **extra) -> str:
        """sampling を省くと v2 の設定。extra は response_format など。"""
        body = {"messages": messages, "max_tokens": max_tokens, "stream": False,
                **(SAMPLING if sampling is None else sampling), **extra}
        r = requests.post(self.url, json=body, timeout=60)
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()

    def ping(self):
        self.complete([{"role": "user", "content": "こんにちは"}], 8)

    # ---- プロンプト
    @staticmethod
    def learned_block(words: Optional[List[str]]) -> str:
        """Cloud Functions から渡された覚えた言葉（最新20個）をプロンプト用の文にする。"""
        ws = []
        for w in (words or [])[-LEARNED_IN_PROMPT:]:
            w = norm(str(w))[:LEARN_MAXLEN]
            if w and not BAD.search(w) and w not in ws:
                ws.append(w)
        if not ws:
            return ""
        return ("\n\n【覚えている言葉】これまでの飼い主から教わった言葉。話の流れに合うときだけ、自然に1つ使ってよい。"
                "無理に使わない。\n" + "、".join(ws))

    def system_prompt(self, style: Optional[str] = None, learned: Optional[List[str]] = None) -> str:
        o = OWNERS.get(style or "") or OWNERS[self.style]
        base = SYSTEM.format(pet=self.pet, speech=o["speech"], state=o["state"],
                             examples=o["examples"].format(pet=self.pet))
        # 性格は話し方（飼い主から移ったもの）より優先して、返事の長さ・勢いを決める
        return base + f"""

【あなたの性格】話し方の記録より、こちらを優先する。「！」は使ってよい。
{PERSONA}

【返事の書き方】返事の本文だけを書く。先頭に「{self.pet}「」や名前、かぎかっこを付けない。""" + self.learned_block(learned)

    # ---- 返事
    def reply(self, hist: List[dict], user_text: str, style: Optional[str] = None,
              learned: Optional[List[str]] = None) -> str:
        msgs = [{"role": "system", "content": self.system_prompt(style, learned)}]
        for h in hist[-N_HIST:]:
            owner = h["speaker"] in ("owner", "飼い主")
            msgs.append({"role": "user" if owner else "assistant",
                         "content": h["text"] if owner else clean_reply(h["text"], self.pet)})
        msgs.append({"role": "user", "content": user_text})
        return cut(clean_reply(self.complete(msgs), self.pet)) or "うん、うん。"
