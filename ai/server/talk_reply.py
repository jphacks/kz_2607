"""
talk_reply.py — 決まった振り分け（action）から返事を作る。使えないときは 8080（LoRA なし）→ 決まった返事
"""
from typing import List

from common import PetProfile
from memory import dont_know_reply as memory_dont_know
from pet_self import chat_extra, question_kind, template
from talk_models import M

SAFE_REPLIES = [
    "うーん、そのお話はちょっとむずかしいな。ほかのお話しよ？",
    "それはよくわからないや。ねえ、今日はなにしてたの？",
]


def make_reply(action: str, req, profile: PetProfile, hist: List[dict], user_text: str,
               learned, errors: List[str], memory_or_chat: bool = False, past_hint: bool = False):
    """判定の結果から返事を作る。返り値: (返事, generator, persona)。失敗したら 8080 → 決まった返事へ。
    memory_or_chat … 判定が雑談か思い出かで迷った（「思い出（検索して無ければ雑談）」）。思い出が無ければ雑談で返す
    past_hint      … ペット自身の「前のこと」から回してきた。memory.py で必ず前の代として探す"""
    if action == "思い出":
        try:
            r = M.memory.reply(profile, hist, user_text, req.memories, req.nameMap, req.journeys, past_hint=past_hint,
                               past_memories=req.pastMemories, summarized_seq=req.summarizedSeq, facts=req.facts)
            if not (memory_or_chat and r[1] == "memory-dontknow"):
                return r
            action = "雑談"                  # 迷っていたときは「覚えてない」より雑談で返す（下の雑談へ）
        except Exception as e:
            errors.append(f"memory: {e}")
            # 作り話を避けるため 8080 には回さず「覚えてない」
            return memory_dont_know("current", profile), "memory-dontknow", {"stage": profile.stage,
                                                                        "memory": {"check": "error"}}
    if action == "雑談" and M.chat.ready:
        try:
            extra = chat_extra(profile)
            reply, persona = M.chat.reply(profile, hist, user_text, extra=extra)
            if reply:
                return reply, "lfm2.5-lora-t04b", persona
        except Exception as e:
            errors.append(f"chat_lora: {e}")
    if action == "ペット自身":
        try:
            return M.pet_self.reply(profile, hist, user_text)
        except Exception as e:
            errors.append(f"pet_self: {e}")
            # 作り話を避けるため 8080 には回さず、プロフィールだけの決まった返事
            kind = question_kind(user_text)
            return M.pet_self._finish(template(kind, profile), profile), "self-template", {"stage": profile.stage,
                                                               "self": {"kind": kind, "fact_check": "error"}}
    if action == "込み入った質問":
        try:
            reply, persona, generator = M.complex.reply(profile, hist, user_text)
            if reply:
                return reply, generator, persona
        except Exception as e:
            errors.append(f"haiku: {e}")
    # 上が使えないとき → LoRA なし（8080）
    try:
        return M.base.reply(hist, user_text, req.style, learned), "lfm2.5-base", None
    except Exception as e:
        errors.append(f"llm: {e}")
        return "ちょっとぼーっとしてた。もう一回言って？", "fallback", None
