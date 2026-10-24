"""
talk_route.py — 判定モデルの決定（action）を、言葉で上書きする（振り分けの最後の調整）
  ・雑談か思い出かで迷った（「思い出（検索して無ければ雑談）」）→ 思い出を探し、無ければ雑談
  ・最新の話題・深刻な悩み → 込み入った質問（force_complex）
  ・「覚えてる？」「〜したっけ」→ 思い出（is_recall）。ペット自身にされても、ペットのことを聞いていなければ思い出
  ・ペット自身の「前はどこにいたの？」→ 思い出（前の代として探す）
"""
import re
import unicodedata
from typing import Tuple

from complex_question import force_complex
from memory import is_recall
from pet_self import question_kind

# ペット自身のことを聞いている言葉（これがあれば「〜っけ」でもペット自身のまま）
ABOUT_PET_RE = re.compile(r"きみの|君の|キミの|お前の|おまえの|自分の|何代目|なんだいめ|何歳|なんさい|誕生日|生まれ|名前|なまえ|"
                          r"好きな|すきな|嫌いな|きらいな|旅|ゲージ|お別れ|おわかれ|何の動物|種類")


def adjust_action(j: dict, user_text: str) -> Tuple[bool, bool]:
    """j["action"]・j["override"] を書きかえる。返り値: (memory_or_chat, past_hint)
    memory_or_chat … 思い出が見つからなければ雑談で返す
    past_hint      … 思い出は必ず前の代として探す"""
    j["override"] = None
    # 判定が雑談か思い出かで迷ったとき（judge_infer の「思い出（検索して無ければ雑談）」）は、まず思い出を探す。
    # そのままだとどの振り分けにも当たらず 8080（LoRA なし）に落ちていた
    memory_or_chat = j["action"].startswith("思い出（")
    if memory_or_chat and is_recall(user_text):     # 「覚えてる？」とはっきり聞いたなら、無ければ「覚えてない」
        memory_or_chat = False
        j["override"] = "迷い→思い出（はっきり聞いた）"
        j["action"] = "思い出"
    if memory_or_chat:
        j["override"] = f"{j['action']}→思い出（無ければ雑談）"
        j["action"] = "思い出"
    past_hint = False
    # 判定モデルが拾えない最新の話題・深刻な悩みを、言葉で込み入った質問に回す（仮）
    if j["action"] in ("雑談", "ペット自身", "思い出"):
        why = force_complex(user_text)
        if why:
            j["override"] = f"{j['action']}→込み入った質問（{why}）"
            j["action"] = "込み入った質問"
            memory_or_chat = False
    # 判定モデルは「前に話したこと」を雑談にしやすいので、言葉で思い出に回す（仮）
    if j["action"] == "雑談":
        why = is_recall(user_text)
        if why:
            j["override"] = f"雑談→思い出（{why}）"
            j["action"] = "思い出"
    # 判定モデルがペット自身にした「〜っけ」「覚えてる？」でも、ペットのことを聞いていなければ思い出に回す
    # （例：「去年行った大学はどこだっけ？」がペット自身になり「わかんないよ」と返していた）
    if j["action"] == "ペット自身" and question_kind(user_text) != "past":
        why = is_recall(user_text)
        if why and not ABOUT_PET_RE.search(unicodedata.normalize("NFKC", user_text)):
            j["override"] = f"ペット自身→思い出（{why}）"
            j["action"] = "思い出"
    # ペット自身の「前はどこにいたの？」は旅の記録で答える
    if j["action"] == "ペット自身" and question_kind(user_text) == "past":
        j["override"] = "ペット自身→思い出（前のこと）"
        j["action"] = "思い出"
        past_hint = True
    return memory_or_chat, past_hint
