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
    talk_server.py        … これ。FastAPI・振り分け
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
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from base_llm import BaseLLM
from chat_lora import ChatLoRA
from common import ENV_FILE, GENERATION_BASE, JUDGE_DIR, PET_NAME, TEACHER_DIR, TEACHER_ERR, PetProfile
from complex_question import ComplexQuestion, force_complex
from judge_model import JudgeModel
from learn_words import WordLearner
from memory import MemoryTalk, dont_know_reply as memory_dont_know, is_recall
from pet_self import PET_SELF_PROMPT, PET_SELF_TEMP, PROFILE_IN_CHAT, PetSelf, chat_extra, question_kind, template

API_KEY = os.environ.get("TALK_API_KEY", "")
KEEP_TURNS = 12       # ペットごとに覚えておく発言の数（メモリの中だけ）
SAFE_REPLIES = [
    "うーん、そのお話はちょっとむずかしいな。ほかのお話しよ？",
    "それはよくわからないや。ねえ、今日はなにしてたの？",
]

app = FastAPI(title="pet talk server")
pool = ThreadPoolExecutor(max_workers=8)    # 覚える言葉の抽出を返事の生成と同時に走らせる（同時に来た人の分も）
# 同時に来たときの鍵（10/24 に分けた）
#   judge_lock … 判定モデルだけ1件ずつ（キャッシュを同時に触らないため）。20〜45 ms で外れる
#   ペットごとの鍵 … 同じペットに同時に来たときだけ順番にする（history が混ざらないように）
#   返事の生成（8081・Haiku・8080）は鍵の外。Haiku の待ちでほかの人を止めない。8081 は llama-server が順番に処理する
judge_lock = threading.Lock()
_pet_locks: dict = {}
_pet_locks_guard = threading.Lock()
history = defaultdict(list)                 # petId → [{"speaker": "owner"|"pet", "text": ...}]


def pet_lock(pet_id: str) -> threading.Lock:
    with _pet_locks_guard:
        if pet_id not in _pet_locks:
            _pet_locks[pet_id] = threading.Lock()
        return _pet_locks[pet_id]


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


@app.on_event("startup")
def startup():
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


# ---------------------------------------------------------------- 振り分け
def make_reply(action: str, req: TalkRequest, profile: PetProfile, hist: List[dict], user_text: str,
               learned, errors: List[str]):
    """判定の結果から返事を作る。返り値: (返事, generator, persona)。失敗したら 8080 → 決まった返事へ。"""
    if action == "思い出":
        try:
            return M.memory.reply(profile, hist, user_text, req.memories, req.nameMap, req.journeys)
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


@app.post("/talk")
def talk(req: TalkRequest, x_api_key: Optional[str] = Header(default=None)):
    check_key(x_api_key)
    if not req.text or not req.text.strip():
        raise HTTPException(400, "text を送ってください")

    with pet_lock(req.petId):
        T0 = time.perf_counter()
        ms, errors = {"wait": 0.0, "judge": 0.0, "gen": 0.0, "learn": 0.0}, []
        user_text = req.text.strip()

        hist = [t.model_dump() for t in req.history] if req.history is not None else history[req.petId]
        profile = PetProfile.from_request(req)

        # 2. 判定
        t = time.perf_counter()
        with judge_lock:
            ms["wait"] = (time.perf_counter() - t) * 1000          # 判定の順番待ち（同時に来たときだけ増える）
            j = M.judge(hist + [{"speaker": "owner", "text": user_text}])
        # 判定モデルが拾えない最新の話題・深刻な悩みを、言葉で込み入った質問に回す（仮）
        j["override"] = None
        if j["action"] in ("雑談", "ペット自身", "思い出"):
            why = force_complex(user_text)
            if why:
                j["override"] = f"{j['action']}→込み入った質問（{why}）"
                j["action"] = "込み入った質問"
        # 判定モデルは「前に話したこと」を雑談にしやすいので、言葉で思い出に回す（仮）
        if j["action"] == "雑談":
            why = is_recall(user_text)
            if why:
                j["override"] = f"雑談→思い出（{why}）"
                j["action"] = "思い出"
        # ペット自身の「前はどこにいたの？」は旅の記録で答える
        if j["action"] == "ペット自身" and question_kind(user_text) == "past":
            j["override"] = "ペット自身→思い出（前のこと）"
            j["action"] = "思い出"
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
            reply, generator, persona = make_reply(j["action"], req, profile, hist, user_text, learned, errors)
            if fut is not None:
                try:
                    learn_words = fut.result(timeout=30)
                except Exception as e:
                    errors.append(f"learn: {e}")
        ms["gen"] = (time.perf_counter() - t) * 1000

        # 差し替えた返事もそのまま残る（作り話を history からくり返さないように、表に出した返事だけを覚える）
        if req.history is None:
            history[req.petId] = (hist + [{"speaker": "owner", "text": user_text},
                                          {"speaker": "pet", "text": reply}])[-KEEP_TURNS:]
        ms["total"] = (time.perf_counter() - T0) * 1000
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
        print(f"[talk] {time.strftime('%H:%M:%S')} pet={req.petId} | 飼い主「{user_text}」→ {profile.name}「{reply}」"
              f" | {generator}{p_log} | 覚える{learn_words} | {j['action']}"
              + (f"（{j['override']}）" if j.get("override") else "") + f" 危険{j['unsafe_prob']}"
              f" | 判定{ms['judge']:.0f}ms（待ち{ms['wait']:.0f}） 生成{ms['gen']:.0f}ms 合計{ms['total']:.0f}ms"
              + (f" | エラー {errors}" if errors else ""), flush=True)

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
    history.pop(petId, None)
    return {"ok": True}


if __name__ == "__main__":  # python talk_server.py でも起動できるようにする
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")))