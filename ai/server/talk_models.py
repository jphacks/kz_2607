"""
talk_models.py — 起動時に作るモデルたち（判定・雑談の性格LoRA・ペット自身・込み入った質問・思い出・覚える言葉）
"""
import time
from typing import Optional

from base_llm import BaseLLM
from chat_lora import ChatLoRA
from common import ENV_FILE, GENERATION_BASE, JUDGE_DIR
from complex_question import ComplexQuestion
from judge_model import JudgeModel
from learn_words import WordLearner
from memory import MemoryTalk
from pet_self import PET_SELF_PROMPT, PET_SELF_TEMP, PROFILE_IN_CHAT, PetSelf
from talk_state import judge_lock


class Models:
    """起動時に作るモデルたち。"""
    judge: Optional[JudgeModel] = None
    base = BaseLLM()
    learner = WordLearner(base)
    chat = ChatLoRA()
    pet_self = PetSelf(chat)
    complex = ComplexQuestion()
    memory = MemoryTalk(chat)


M = Models()


def load_models() -> None:
    """サーバーの起動時に1回だけ呼ぶ。"""
    print(f"[startup] .env: {ENV_FILE or '見つからない（export した値を使う）'}")
    t0 = time.time()
    M.judge = JudgeModel()
    print(f"[startup] judge ready ({time.time() - t0:.1f}s)  code: {JUDGE_DIR}  ckpts: {M.judge.ckpts}")
    try:
        M.base.ping()
        print("[startup] llama-server（LoRA なし・8080）ok")
    except Exception as e:
        print(f"[startup] llama-server（LoRA なし・8080）NG: {e}")
    M.chat.load()
    t0 = time.time()
    if M.memory.embedder.attach(getattr(M.judge, "runner", None)):
        M.memory.embedder.lock = judge_lock          # 判定と同じ Ruri を使うので、判定と同じ鍵で順番にする
    else:
        M.memory.embedder.load()
    print(f"[startup] 思い出: {M.memory.embedder.status}（{time.time() - t0:.1f}s）下限 {M.memory.embedder.min_sim}"
          f"・温度 {M.memory.temperature}")
    print(f"[startup] 性格LoRA（{M.chat.url}）{M.chat.status}")
    print(f"[startup] ペット自身: 性格LoRA＋プロフィール（温度 {PET_SELF_TEMP}・プロンプト {PET_SELF_PROMPT}）・事実のチェック。"
          f"雑談へのプロフィール: {'入れる' if PROFILE_IN_CHAT else '入れない'}（PROFILE_IN_CHAT）。"
          f"generation は {GENERATION_BASE} から数える")
    if M.complex.enabled:
        print(f"[startup] 込み入った質問: Haiku（{M.complex.model}）。赤ちゃんの段階は決まった返事")
    else:
        print("[startup] 込み入った質問: ANTHROPIC_API_KEY が無いので 8080 で返す（赤ちゃんの段階は決まった返事）")
