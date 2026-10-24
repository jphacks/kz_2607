"""
talk_server.py — Cloud Functions から呼ばれる会話サーバー（受け取り・振り分け・返すだけ）

  文字 → 判定モデル → 振り分け → 返事（音声の変換は Cloud Functions が行う）
    雑談           : ChatLoRA        （chat_lora.py・性格LoRA の LFM2.5・8081）
    思い出         : MemoryTalk      （memory.py・Ruri で思い出を選ぶ ＋ 性格LoRA ＋ チェック。無ければ「覚えてない」）
                     ペット自身の「前はどこにいたの？」も memory.py へ（旅の記録 journeys で答える）
    ペット自身     : PetSelf         （pet_self.py・性格LoRA ＋ プロフィール ＋ 事実のチェック。外れたら決まった返事）
    込み入った質問 : ComplexQuestion （complex_question.py・赤ちゃんは決まった返事、子ども・育ったは Haiku）
    ほかが使えないとき : BaseLLM（base_llm.py・LoRA なしの LFM2.5・8080）
    安全な返事     : 決まった返事
  覚える言葉は WordLearner（learn_words.py）が返事と同時に作る

ファイル（同じフォルダに置く。置き場所は judge_code/server・chat/talk/server・talk/server のどれでもよい。
          judge_infer.py は server と同じ位置の test_server/ に置く。teacher_data.py・判定の重みは上のフォルダから自動で探す）
    talk_server.py        … これ。FastAPI で受け取って、順番に呼んで、返すだけ
    talk_state.py         … 直前の会話（history）・同時に来たときの鍵・代が変わったら会話を消す
    talk_models.py        … 起動時に作るモデルたち（Models・load_models）
    talk_route.py         … 判定の決定を言葉で上書きする（迷い・込み入った質問・思い出・前のこと）
    talk_reply.py         … 振り分けから返事を作る（make_reply）
    talk_log.py           … 1行ログ
    common.py             … 共通（PetProfile・プロフィールの文・後片付け・性格の軸）
    judge_model.py        … 判定モデル JudgeModel
    chat_lora.py          … 雑談 ChatLoRA
    pet_self.py           … ペット自身 PetSelf（事実のチェック・決まった返事）
    memory.py             … 思い出 MemoryTalk（今の飼い主の memories・前の代の journeys）
    check_memory.py       … 思い出の確認用
    complex_question.py   … 込み入った質問 ComplexQuestion
    base_llm.py           … LoRA なし BaseLLM
    learn_words.py        … 覚える言葉 WordLearner
    check_complex.py      … 込み入った質問の確認用
    check_pet_self.py     … ペット自身の確認用（実験A）
    .env                  … ANTHROPIC_API_KEY・TALK_API_KEY（Git に入れない）

起動:
    cd judge_for_mac/server
    source ../chat/.venv/bin/activate
    uvicorn talk_server:app --host 0.0.0.0 --port 8000

環境変数: TALK_API_KEY・ANTHROPIC_API_KEY・HAIKU_MODEL・LLAMA_URL・CHAT_LLAMA・TEACHER_DIR・LORA_TOPK・LORA_SCALE・
         PET_NAME・PET_STYLE・JUDGE_CKPTS・PET_SELF_TEMP・PET_SELF_PROMPT・PROFILE_IN_CHAT・GENERATION_BASE・
         MEMORY_MIN_SIM・MEMORY_TEMP・MEMORY_RURI（意味は各ファイルの先頭）
"""
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from common import PET_NAME, TEACHER_DIR, TEACHER_ERR, PetProfile
from pet_self import PET_SELF_PROMPT, PET_SELF_TEMP, PROFILE_IN_CHAT
from talk_log import log_talk
from talk_models import M, load_models
from talk_reply import SAFE_REPLIES, make_reply
from talk_route import adjust_action
from talk_state import forget_if_new_generation, get_history, judge_lock, pet_lock, remember, reset as reset_state

API_KEY = os.environ.get("TALK_API_KEY", "")

app = FastAPI(title="pet talk server")
pool = ThreadPoolExecutor(max_workers=8)    # 覚える言葉の抽出を返事の生成と同時に走らせる（同時に来た人の分も）


@app.on_event("startup")
def startup():
    load_models()


# ---------------------------------------------------------------- API の形
class Turn(BaseModel):
    speaker: str          # "owner" | "pet"
    text: str


class TalkRequest(BaseModel):
    petId: str = "demo"
    text: str                           # 飼い主の発言（Cloud Functions が音声から変換した文字）
    history: Optional[List[Turn]] = None  # 送られてきたらサーバーの記憶より優先
    style: Optional[str] = None         # base_llm.OWNERS のキー（8080 で返すとき）
    learned_words: Optional[List[str]] = None   # ペットが覚えている言葉（最新20個）。learnedWords でも可
    learnedWords: Optional[List[str]] = None
    want_learn: bool = True             # false なら learn_words を作らない
    # ---- ペットの情報（どれも省略可）
    petName: Optional[str] = None
    personalityAxes: Optional[Dict[str, float]] = None  # 6軸の値
    humanness: Optional[float] = None                 # 0・0.5・1。無ければ育った段階
    birthTrait: Optional[str] = None                  # 誕生時に一番強かった軸
    firstPerson: str = "ぼく"
    ownerStyle: Optional[str] = None                  # 標準・関西弁・敬語・若者言葉、または話し方の説明文
    hour: Optional[int] = None                        # 今の時刻（0〜23）。無ければサーバーの日本時間
    # ---- ペット自身の返事に使う（どれも省略可。型が違っても PetProfile でそろえる）
    baseType: Optional[str] = None                    # 種族（dog_type など）
    bornAt: Optional[Any] = None                      # 生まれた日（ISO 文字列。Timestamp・UNIX 時刻でも読む）
    generation: Optional[Any] = None                  # 今の代
    ownerCount: Optional[Any] = None                  # 今の飼い主が何人目か（無ければ generation から）
    # ---- 思い出に使う（どれも省略可。memory.py の先頭を参照）
    memories: Optional[List[Dict[str, Any]]] = None   # 今の飼い主との思い出（伏せ字入り・最近30件ほど）
    nameMap: Optional[Dict[str, Any]] = None          # 今の飼い主の伏せ字 → 本当の名前
    journeys: Optional[List[Dict[str, Any]]] = None   # 前の代との思い出（1代1件）
    pastMemories: Optional[List[Dict[str, Any]]] = None  # 前の代の思い出（ぼかし済み。直前の代 最大7件＋1代目 最大3件）


@app.get("/health")
def health():
    return {"ok": M.judge is not None, "pet": PET_NAME,
            "chat_lora": {"url": M.chat.url, "lora": M.chat.lora_ids, "topk": M.chat.topk, "scale": M.chat.scale,
                          "teacher": str(TEACHER_DIR) if TEACHER_DIR else None, "error": TEACHER_ERR},
            "pet_self": {"temperature": PET_SELF_TEMP, "prompt": PET_SELF_PROMPT, "profile_in_chat": PROFILE_IN_CHAT},
            "memory": {"embedder": M.memory.embedder.status, "min_sim": M.memory.embedder.min_sim,
                       "temperature": M.memory.temperature},
            "haiku": {"enabled": M.complex.enabled, "model": M.complex.model}}


def check_key(x_api_key: Optional[str]):
    """合い言葉（X-Api-Key）を確かめる。合わない理由をログとエラーに出す（中身は出さない）。"""
    if not API_KEY:
        return
    if not x_api_key:
        print("[auth] 401: X-Api-Key ヘッダーがない（Cloud Functions の Secret が空か、ヘッダーを付けていない）")
        raise HTTPException(401, "X-Api-Key ヘッダーがありません（Cloud Functions の Secret が空の可能性）")
    if x_api_key != API_KEY:
        hint = "前後に空白や改行がある" if x_api_key.strip() == API_KEY else f"値が違う（受け取った長さ {len(x_api_key)}・正しい長さ {len(API_KEY)}）"
        print(f"[auth] 401: X-Api-Key が一致しない — {hint}")
        raise HTTPException(401, f"X-Api-Key が一致しません — {hint}")


@app.post("/talk")
def talk(req: TalkRequest, x_api_key: Optional[str] = Header(default=None)):
    check_key(x_api_key)
    if not req.text or not req.text.strip():
        raise HTTPException(400, "text を送ってください")

    with pet_lock(req.petId):
        T0 = time.perf_counter()
        ms, errors = {"wait": 0.0, "judge": 0.0, "gen": 0.0, "learn": 0.0}, []
        user_text = req.text.strip()

        forget_if_new_generation(req.petId, req.generation)
        hist = get_history(req.petId, [t.model_dump() for t in req.history] if req.history is not None else None)
        profile = PetProfile.from_request(req)

        # 2. 判定
        t = time.perf_counter()
        with judge_lock:
            ms["wait"] = (time.perf_counter() - t) * 1000          # 判定の順番待ち（同時に来たときだけ増える）
            j = M.judge(hist + [{"speaker": "owner", "text": user_text}])
        memory_or_chat, past_hint = adjust_action(j, user_text)
        ms["judge"] = (time.perf_counter() - t) * 1000

        # 3. 生成（＋覚える言葉の抽出を同時に）
        learned = req.learned_words if req.learned_words is not None else req.learnedWords
        learn_words: List[str] = []
        persona = None
        t = time.perf_counter()
        if j["action"] == "安全な返事":                  # 危ない発言からは何も覚えない
            reply, generator = random.choice(SAFE_REPLIES), "safe"
        else:
            fut = None
            if req.want_learn:
                def _learn():
                    t1 = time.perf_counter()
                    try:
                        return M.learner(user_text)
                    finally:
                        ms["learn"] = (time.perf_counter() - t1) * 1000
                fut = pool.submit(_learn)
            reply, generator, persona = make_reply(j["action"], req, profile, hist, user_text, learned, errors,
                                                   memory_or_chat=memory_or_chat, past_hint=past_hint)
            if memory_or_chat and not generator.startswith("memory"):
                j["override"] = (j["override"] or "") + "→雑談（思い出が見つからない）"
            if fut is not None:
                try:
                    learn_words = fut.result(timeout=30)
                except Exception as e:
                    errors.append(f"learn: {e}")
        ms["gen"] = (time.perf_counter() - t) * 1000

        if req.history is None:
            remember(req.petId, hist, user_text, reply)
        ms["total"] = (time.perf_counter() - T0) * 1000
        pet_self = (persona or {}).get("self")
        mem = (persona or {}).get("memory")
        log_talk(req.petId, user_text, profile.name, reply, generator, persona, learn_words, j, ms, errors)

    return {
        "user_text": user_text,
        "reply_text": reply,
        "learn_words": learn_words,
        "route": j["action"],
        "generator": generator,
        "persona": persona,
        "pet_self": pet_self,
        "memory": mem,
        "judge": {"route": j["route"], "route_probs": j["route_probs"], "unsafe_prob": j["unsafe_prob"],
                  "override": j.get("override"),
                  "emotion": j["emotion"], "intensity": j["intensity"]},
        "timings_ms": {k: round(v, 1) for k, v in ms.items()},
        "errors": errors,
    }


@app.post("/reset")
def reset(petId: str = "demo", x_api_key: Optional[str] = Header(default=None)):
    check_key(x_api_key)
    reset_state(petId)
    return {"ok": True}


if __name__ == "__main__":  # python talk_server.py でも起動できるようにする
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")))
