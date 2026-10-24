"""
talk_log.py — /talk の1行ログ（だれが何を言い、どの振り分け・どのモデルで返したか、時間）
"""
import time
from typing import List, Optional


def log_talk(pet_id: str, user_text: str, pet_name: str, reply: str, generator: str, persona: Optional[dict],
             learn_words: List[str], j: dict, ms: dict, errors: List[str]) -> None:
    pet_self = (persona or {}).get("self")
    mem = (persona or {}).get("memory")
    p_log = ""
    if persona:
        p_log = f" {persona.get('scales') or persona.get('top2') or ''} 段階{persona.get('stage')}"
        if persona.get("tokens"):
            p_log += f" tokens{persona['tokens']}"
    if pet_self:
        p_log += f" 種類{pet_self.get('kind')} チェック{pet_self.get('fact_check')}"
        if pet_self.get("reasons"):
            p_log += f"{pet_self['reasons']} 元「{pet_self.get('original', '')}」"
    if mem:
        p_log += (f" 思い出{mem.get('kind')} {mem.get('date') or ''}選んだ{mem.get('picked') or mem.get('generation')}"
                  f" 近さ{mem.get('scores', '')} チェック{mem.get('check')}")
        if mem.get("reasons"):
            p_log += f"{mem['reasons']} 元「{mem.get('original', '')}」"
        if mem.get("why"):
            p_log += f"（{mem['why']}）"
    print(f"[talk] {time.strftime('%H:%M:%S')} pet={pet_id} | 飼い主「{user_text}」→ {pet_name}「{reply}」"
          f" | {generator}{p_log} | 覚える{learn_words} | {j['action']}"
          + (f"（{j['override']}）" if j.get("override") else "") + f" 危険{j['unsafe_prob']}"
          f" | 判定{ms['judge']:.0f}ms（待ち{ms['wait']:.0f}） 生成{ms['gen']:.0f}ms 合計{ms['total']:.0f}ms"
          + (f" | エラー {errors}" if errors else ""), flush=True)
