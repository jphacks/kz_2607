"""
learn_words.py — 覚える言葉の抽出（LoRA なしの LFM2.5・8080 を使う）

発言から覚えるとよい言葉を最大3つ JSON で選ばせ、決まりで絞る。
    learner = WordLearner(base_llm)
    words = learner(user_text)    # ["みかん"]
"""
import json
import re
from typing import List

from base_llm import BaseLLM
from common import BAD, PET_NAME, norm

LEARN_MAX, LEARN_MAXLEN = 3, 20
LEARN_PROMPT = """あなたは、ペットが飼い主の話から覚える言葉を選ぶ係です。
飼い主の発言から、覚えるとよい言葉を、発言に出てきた形のまま最大3つ選んでください。
- 選ぶもの: 好きなもの・食べ物・遊び・趣味、人や場所や作品などの名前、気持ちを表す言葉（うれしい・悲しい など）
- 選ばないもの: あいさつ、「今日」「なんか」「これ」などのありふれた言葉、文や命令、URL・メールアドレス・電話番号・数字だけのもの
- 覚えるものがなければ空の配列
例:
「みかん好きなんだよね」→ {"words": ["みかん"]}
「今日たけしと公園でサッカーした」→ {"words": ["たけし", "公園", "サッカー"]}
「テスト悪くて悲しい」→ {"words": ["テスト", "悲しい"]}
「ただいま」→ {"words": []}
「おなかすいた」→ {"words": []}"""
LEARN_SCHEMA = {"type": "object", "required": ["words"],
                "properties": {"words": {"type": "array", "maxItems": LEARN_MAX,
                                         "items": {"type": "string", "minLength": 1, "maxLength": LEARN_MAXLEN}}}}
GREETINGS = {"ただいま", "おかえり", "おはよう", "おやすみ", "こんにちは", "こんばんは", "いってきます", "いってらっしゃい",
             "ありがとう", "ごめん", "ばいばい", "またね", "よろしく"}
COMMON = {"今日", "明日", "昨日", "今", "なんか", "これ", "それ", "あれ", "ここ", "そこ", "こと", "もの", "とき", "感じ",
          "自分", "みんな", "私", "僕", "俺", "あなた", "きみ", "君", "お前", "ちょっと", "めっちゃ", "すごい", "やばい", "本当"}
def filter_words(words, user_text: str, pet: str) -> List[str]:
    """選んだ言葉を決まりで絞る: 発言に実際に出てくる・20文字以内・あいさつやありふれた言葉、URL・連絡先・指示は除く・最大3語。"""
    src, out = norm(user_text), []
    for w in words or []:
        w = norm(str(w)).strip("「」『』\"'、。！？!?・ ")
        if not w or len(w) > LEARN_MAXLEN or w in out:
            continue
        if w not in src:                                   # 発言に出てこない言葉（作り話）は覚えない
            continue
        if w in GREETINGS or w in COMMON or w == pet or BAD.search(w):
            continue
        if re.fullmatch(r"[ぁ-ん]", w) or re.fullmatch(r"[\d\W_]+", w):   # 1文字のひらがな・記号や数字だけ
            continue
        out.append(w)
        if len(out) >= LEARN_MAX:
            break
    return out


class WordLearner:
    def __init__(self, llm: BaseLLM, pet: str = PET_NAME):
        self.llm, self.pet = llm, pet

    def __call__(self, user_text: str) -> List[str]:
        raw = self.llm.complete(
            [{"role": "system", "content": LEARN_PROMPT}, {"role": "user", "content": f"「{user_text}」"}],
            max_tokens=64, sampling={"temperature": 0},
            response_format={"type": "json_schema", "json_schema": {"name": "learn", "schema": LEARN_SCHEMA}})
        try:
            words = json.loads(raw).get("words", [])
        except Exception:
            m = re.search(r"\[.*?\]", raw, re.S)
            words = json.loads(m.group(0)) if m else []
        return filter_words(words, user_text, self.pet)
