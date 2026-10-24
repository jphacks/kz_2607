"""
talk_state.py — サーバーがメモリの中だけで持つもの：ペットごとの直前の会話（history）・同時に来たときの鍵
  ・交換で代（generation）が変わったら、覚えていた直前の会話を消す（前の飼い主の話が新しい飼い主の文脈に入らないように）
"""
import threading
from collections import defaultdict
from typing import List, Optional

KEEP_TURNS = 12       # ペットごとに覚えておく発言の数（メモリの中だけ）
# 同時に来たときの鍵（10/24 に分けた）
#   judge_lock … 判定モデルだけ1件ずつ（キャッシュを同時に触らないため）。20〜45 ms で外れる
#   ペットごとの鍵 … 同じペットに同時に来たときだけ順番にする（history が混ざらないように）
#   返事の生成（8081・Haiku・8080）は鍵の外。Haiku の待ちでほかの人を止めない。8081 は llama-server が順番に処理する
judge_lock = threading.Lock()
_pet_locks: dict = {}
_pet_locks_guard = threading.Lock()
history = defaultdict(list)                 # petId → [{"speaker": "owner"|"pet", "text": ...}]
_last_gen: dict = {}                        # petId → 最後に見た generation（交換で変わったら history を消す）


def pet_lock(pet_id: str) -> threading.Lock:
    with _pet_locks_guard:
        if pet_id not in _pet_locks:
            _pet_locks[pet_id] = threading.Lock()
        return _pet_locks[pet_id]


def forget_if_new_generation(pet_id: str, generation) -> None:
    """受け取った generation が前回と違ったら、覚えていた直前の会話を消す。"""
    # 交換で代が変わったら、サーバーが覚えている直前の会話（前の飼い主の発言）を消す。
    # 消さないと、新しい飼い主の1回目の判定・返事に前の飼い主の話が文脈として入る
    gen = str(generation) if generation is not None else None
    if gen is not None:
        if _last_gen.get(pet_id) not in (None, gen):
            history.pop(pet_id, None)
            print(f"[talk] pet={pet_id} 代が {_last_gen[pet_id]} → {gen} に変わったので、覚えていた会話を消しました",
                  flush=True)
        _last_gen[pet_id] = gen


def get_history(pet_id: str, sent: Optional[List[dict]]) -> List[dict]:
    """送られてきた history があればそれ、無ければサーバーが覚えている分。"""
    return sent if sent is not None else history[pet_id]


def remember(pet_id: str, hist: List[dict], user_text: str, reply: str) -> None:
    """表に出した返事だけを覚える（差し替えた返事もそのまま。作り話を history からくり返さないように）。"""
    history[pet_id] = (hist + [{"speaker": "owner", "text": user_text},
                               {"speaker": "pet", "text": reply}])[-KEEP_TURNS:]


def reset(pet_id: str) -> None:
    history.pop(pet_id, None)
    _last_gen.pop(pet_id, None)
