"""
memory.py — 思い出の返事（判定が「思い出」、またはペット自身の「前のこと」）

語り方はペット自身と同じ「何を話すかは Mac が決め、性格LoRA は口調だけ」。学習はしない。
    mt = MemoryTalk(chat)                    # chat = ChatLoRA
    mt.embedder.attach(judge.runner)         # 判定モデルの Ruri を使い回す（できなければ自分で読む）
    reply, generator, persona = mt.reply(profile, hist, user_text, memories, name_map, journeys)
    persona["memory"] = {"kind", "picked", "scores", "date", "check", "reasons", ...}

流れ
  1. どちらの思い出か（memory_kind）
       first   … 最初の飼い主（journeys の一番小さい generation）
       past    … 前の飼い主・前はどこ（今の代のひとつ前）
       current … それ以外（今の飼い主との memories）
  2. 今の飼い主：Ruri で今の発言に近い思い出を最大2件。「昨日」「先週」などがあれば日本時間の日付でしぼる
  3. 無い・近さが足りない → モデルを呼ばず「覚えてないなぁ」
  3'. 前の代は、質問の種類（どんな人・教えてもらった言葉・変わったこと・いつ）で旅の記録の値を並べ替え、
       いちばん合う値で答える（order_by_question）
  4. ある → 伏せ字を戻して（今の飼い主は本当の名前、前の代は「あのお店」などにぼかす）【覚えていること】に書き、
     今の発言に答えのヒントを付けて性格LoRA（温度 MEMORY_TEMP）で言わせる
  5. チェック（伏せ字が残っていない・思い出の言葉を使っている・「覚えてない」と言っていない・
     前の代の話に今の飼い主の名前が出ていない）→ 外れたら決まった返事

/talk で受け取るもの（どれも省略可）
    pastMemories : [{"id": "m31", "text": "あのお店でパンを分けてもらった", "generation": 1, "createdAt": "..."}]
                   … 前の代の思い出（バックエンドでぼかし済み。直前の代 最大7件＋1代目 最大3件）。
                     「何してた？」などで今の発言に近いものを1件だけ使う。心配・つらい話は使わない
    memories : [{"id": "m1", "text": "{shop_1}でいちごのアイスを食べた", "createdAt": "2026-10-23T19:00:00+09:00"}]
    nameMap  : {"{shop_1}": "ミスド", "{person_1}": "ゆうと"}   … キーは "shop_1" でもよい
    journeys : [{"generation": 1, "summary": "{place_1}でよく散歩した", "timeOfDay": "夜", "speech": "関西弁",
                 "learnedWords": ["めっちゃ"], "grewTrait": "talkative", "talkCount": 45}]

環境変数:
    MEMORY_MIN_SIM … Ruri の近さの下限（初期値 0.83。check_memory.py --scores-only で決める）
    MEMORY_MIN_LIFT … 1位がほかの思い出（全件の中央値）よりどれだけ近いかの下限（初期値 0.05）
                      Ruri は関係ない文どうしでも 0.8 前後になるので、近さだけでは分けられない
    MEMORY_SECOND_GAP … 2件目を足すのは、1位との差がこれ以下のときだけ（初期値 0.02）
    MEMORY_LIFT_MIN_N … 思い出がこの件数より少ないときは中央値を使わない（初期値 5）
    MEMORY_MIN_LEX … Ruri が読めないとき（文字の重なり）の下限（初期値 0.3）
    MEMORY_TEMP    … 温度（初期値 0.3）
    MEMORY_PROMPT  … react（初期値。思い出の中身は Mac の決まった文で言い、性格LoRA はその思い出への気持ちを一言だけ足す）
                     rewrite（決まった文を性格LoRA に言い直させる）・hint（思い出の中身だけ渡す）。10/24 の確認で react に決めた
    MEMORY_BABY    … template（赤ちゃんの段階はモデルを呼ばず決まった返事。初期値）・model
    MEMORY_RURI    … auto（判定の Ruri → 自分で読む → 文字の重なり）・judge・own・lexical
    RURI_MODEL     … 自分で読むときのモデル（初期値 cl-nagoya/ruri-v3-130m）
（10/25 に処理ごとのファイルに分けた。このファイルは本体 MemoryTalk だけ。ほかの名前もここから読めるようにしてある）
    mem_config.py … 設定（環境変数）
    mem_kind.py   … どちらの思い出か・日付の言葉
    mem_names.py  … 伏せ字を戻す・ぼかす
    mem_embed.py  … 近さ（Ruri・文字の重なり）
    mem_select.py … 今の飼い主の思い出を選ぶ
    mem_past.py   … 前の代（pastMemories・journeys）
    mem_text.py   … 決まった返事・一言の代わり・プロンプト
    mem_check.py  … 返事のチェック
"""
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import mem_config as C
from common import TZ, PetProfile
from mem_check import LEFTOVER_RE, check_reaction, memory_check, trim_to_memory  # noqa: F401
from mem_embed import Embedder, lexical_sim  # noqa: F401
from mem_kind import date_range, day_label, is_recall, memory_kind  # noqa: F401
from mem_names import norm_name_map, unmask  # noqa: F401
from mem_past import (journey_items, journey_lines, order_by_question, parse_past_memories,  # noqa: F401
                      pick_journey, target_generation)
from mem_select import key_hit, parse_facts, parse_memories, pick_facts, recent_items, select_memories  # noqa: F401
from mem_text import (_ends_past, build_extra, build_hint, build_react_hint, build_rewrite_hint,  # noqa: F401
                      dont_know_reply, fact_say, fallback_reaction, template_reply)


# ---------------------------------------------------------------- 本体
class MemoryTalk:
    def __init__(self, chat, embedder: Optional[Embedder] = None, temperature: float = C.MEMORY_TEMP):
        self.chat, self.temperature = chat, temperature
        self.embedder = embedder or Embedder()

    def materials(self, kind: str, p: PetProfile, user_text: str, memories, name_map, journeys,
                  today: date, past_memories=None, hist=None, summarized_seq=None,
                  facts=None) -> Tuple[List[str], dict, str]:
        """【覚えていること】の文・記録・日付の言葉。文が空なら「覚えてない」。facts は parse_facts の結果（今の飼い主のときだけ）"""
        info: Dict[str, Any] = {"kind": kind}
        if kind == "current":
            items = parse_memories(memories, name_map)
            recent = recent_items(hist, user_text, summarized_seq)   # まだ要約されていない直近の会話（飼い主の発言）
            picked, sel = select_memories(self.embedder, user_text, items, name_map, today, recent)
            if os.environ.get("DEBUG_PROMPT"):   # 一時的：直近の候補・要約された思い出・選んだもの
                print(f"[memory] hist={len(hist or [])} recent={[m['text'] for m in recent]} "
                      f"saved={len(items)} picked={[m['text'] for m in picked]} sel={sel}", flush=True)
            info.update(sel)
            info["recent_n"] = len(recent)
            labels = ["さっき" if m.get("recent") else day_label(m["date"], today) for m in picked]
            lines = [(f"さっき、「{m['text']}」と話してくれた" if m.get("recent") else (f"{lb}、" if lb else "") + m["text"])
                     for m, lb in zip(picked, labels)]
            if picked and picked[0].get("recent"):       # 決まった返事は、言った言葉をそのまま引用する（話した順）
                rec = sorted([m for m in picked if m.get("recent")], key=lambda m: int(m["id"].split(":")[1]))
                if p.stage == 1:
                    q = re.sub(r"[、，,！!？?「」\s]", "", picked[0]["text"])   # 赤ちゃんは1つだけ・句読点なし
                    info["_says"] = [f"さっき{q}っていってたよね"]
                else:
                    q = "」「".join(m["text"] for m in rec)
                    info["_says"] = [f"うん、覚えてるよ！さっき「{q}」って話してくれたよね"]
            # 決まった返事用に、1件目の日付の言葉を別に持つ
            info["label"] = labels[0] if picked else ""
            info["_plain"] = [m["text"] for m in picked]
            # 名前・好きなものを聞かれたら、近さによらず事実（facts）で答える。事実を先頭にして、思い出は残りの枠に
            hits = pick_facts(user_text, facts or [])
            if hits:
                info["fact_picked"] = [f["key"] for f in hits]
                info["_says"] = [fact_say(hits[0], p)]
                info["label"] = ""
                lines = ([f["line"] for f in hits] + lines)[:C.MEMORY_TOPK]
                info["_plain"] = ([f["line"] for f in hits] + info["_plain"])[:C.MEMORY_TOPK]
            return lines, info, info["label"]
        gen = target_generation(kind, p, journeys, past_memories)
        info["n"] = len(journeys or [])
        info["generation"] = gen
        j = None
        if gen is not None:
            js = [x.model_dump() if hasattr(x, "model_dump") else x for x in (journeys or [])]
            j = next((x for x in js if isinstance(x, dict) and str(x.get("generation")) in (str(gen), f"{gen}.0")), None)
        items, qtype = order_by_question(journey_items(j, kind, p.first_person, baby=p.stage == 1), user_text) if j else ([], None)
        if qtype is None:
            qtype = order_by_question([], user_text)[1]
        # 前の代の思い出（pastMemories）：「何してた？」など（どんな人・言葉・変わったこと 以外）のとき、
        # 今の発言に近いものがあれば1件だけ先頭に足す。どれも近くなければ旅の記録の値（summary など）で答える
        past, dropped = parse_past_memories(past_memories, gen)
        info["past_n"], info["past_dropped"] = len(past), dropped
        if past and (qtype in ("default", "when") or not items):   # 旅の記録が無ければ、どの質問でも思い出で答える
            picked, sel = select_memories(self.embedder, user_text, past, {}, today)
            info["past_scores"], info["past_why"] = sel.get("scores"), sel.get("why")
            if not picked and not items:            # 旅の記録が無いときは、いちばん新しい思い出で答える
                picked = past[:1]
            if picked:
                m = picked[0]
                who = ("さいしょのかいぬしさん" if kind == "first" else "まえのかいぬしさん") if p.stage == 1 else \
                      ("最初の飼い主さん" if kind == "first" else "前の飼い主さん")
                t = m["text"]
                say = f"{who}とは{t}んだ" if _ends_past(t) else f"{who}とのことは「{t}」って覚えてるよ"
                items = [{"key": "pastMemory", "line": t, "say": say}] + items
                info["picked"] = [m["id"]]
        if not items:
            info["why"] = "旅の記録・前の代の思い出がない"
            return [], info, ""
        lines = [it["line"] for it in items]
        info["question"] = qtype
        info["keys"] = [it["key"] for it in items]
        info["_plain"] = lines
        info["_says"] = [it["say"] for it in items]
        if not lines:
            info["why"] = "旅の記録が空"
        return lines, info, ""

    def reply(self, p: PetProfile, hist: List[dict], user_text: str, memories=None, name_map=None,
              journeys=None, today: Optional[date] = None, past_hint: bool = False, past_memories=None,
              summarized_seq: Optional[int] = None, facts=None):
        """返り値: (返事, generator, persona)。
        past_hint=True … 判定・ペット自身が「前のこと」と決めて回してきたとき。言葉で current になっても past にする
        summarized_seq … バックエンドの summarizedSeq。これ以下の直近の発言は要約と重なるので候補から外す
        facts … 今の飼い主の大事な事実（ownerName・likes）。今の飼い主の話のときだけ【いつも覚えていること】に入れる"""
        today = today or datetime.now(TZ).date()
        name_map = norm_name_map(name_map)
        kind = memory_kind(user_text)
        if past_hint and kind == "current":
            kind = "past"
        fact_items = parse_facts(facts, name_map) if kind == "current" else []   # 前の代の話には入れない
        fact_lines = [f["line"] for f in fact_items]
        lines, info, label = self.materials(kind, p, user_text, memories, name_map, journeys, today, past_memories, hist,
                                            summarized_seq, fact_items)
        plain = info.pop("_plain", [])
        says = info.pop("_says", None)
        if past_hint:
            info["past_hint"] = True
        info.update({"lines": lines, "check": None, "reasons": [], "facts": [f["key"] for f in fact_items]})
        persona_base = {"stage": p.stage}

        if not lines:
            only = kind != "current" and not journeys and not past_memories and p.owners == 1
            info["check"] = "dont_know"
            return dont_know_reply(kind, p, only_owner=only), "memory-dontknow", {**persona_base, "memory": info}

        if not self.chat.ready:
            info["check"] = "template（性格LoRA が使えない）"
            return template_reply(kind, plain, p, label, says), "memory-template", {**persona_base, "memory": info}
        if p.stage == 1 and C.MEMORY_BABY == "template":
            # 赤ちゃん言葉に直すと最初の一文だけ残り、中身が消える（「あのね、いいね！」）ので、モデルを呼ばない
            info["check"] = "baby-template"
            return template_reply(kind, plain, p, label, says), "memory-template", {**persona_base, "memory": info}

        if C.MEMORY_PROMPT == "react":
            return self._react(p, hist, user_text, kind, lines, plain, label, name_map, info, says, fact_lines)

        reply, persona = self.chat.reply(p, hist, user_text, extra=build_extra(kind, lines, p, fact_lines),
                                         sampling={"temperature": self.temperature}, extra_first=True,
                                         model_text=user_text + (build_rewrite_hint(template_reply(kind, plain, p, label, says))
                                                                 if C.MEMORY_PROMPT == "rewrite" else build_hint(kind, plain)))
        info["prompt"] = C.MEMORY_PROMPT
        raw = persona.get("raw") or reply
        if p.stage != 1:
            # おしゃべりの性格LoRA は2文目で自分の体験を作る（「窓の外で小さな鳥が…」）ので、
            # 思い出の言葉が出てくる最後の文までで切る
            trimmed = trim_to_memory(raw, plain)
            if trimmed and trimmed != reply:
                info["trimmed_from"] = reply
                reply = trimmed
            raw = reply
        ok, reasons = memory_check(raw, plain, kind, list(name_map.values()))
        if ok and reply and p.stage != 1 and LEFTOVER_RE.search(reply):
            ok, reasons = False, ["伏せ字が残っている"]
        if ok and reply:
            info["check"] = "ok"
            persona["memory"] = info
            return reply, "lfm2.5-lora-t04b-memory", persona
        info.update({"check": "replaced", "reasons": reasons or ["空の返事"], "original": reply})
        persona["memory"] = info
        return template_reply(kind, plain, p, label, says), "memory-template", persona

    def _react(self, p, hist, user_text, kind, lines, plain, label, name_map, info, says=None, fact_lines=None):
        """思い出の中身は決まった文（必ず正しい）。そのあとに性格LoRA の気持ちの一言を足す。
        一言がチェックに外れたら、決まった文だけ返す。"""
        fact = template_reply(kind, plain, p, label, says)
        info["prompt"] = "react"
        reply, persona = self.chat.reply(p, hist, user_text, extra=build_extra(kind, lines, p, fact_lines),
                                         sampling={"temperature": self.temperature}, extra_first=True,
                                         model_text=user_text + build_react_hint(fact))
        raw = persona.get("raw") or reply
        names = list(name_map.values()) if kind == "current" else []
        reaction, reasons = check_reaction(raw, plain, names, p, fact, facts=fact_lines or [])
        if kind != "current":
            for n in name_map.values():
                if len(n) >= 2 and n in reaction:
                    reasons.append(f"前の代の話に今の飼い主の名前（{n}）")
        info["reaction_raw"] = raw
        if reaction and not reasons:
            info["check"] = "react-ok"
            info["reaction"] = reaction
            persona["memory"] = info
            return fact + reaction, "memory-template+lora", persona
        info.update({"check": "react-dropped", "reasons": reasons})
        persona["memory"] = info
        return fact + fallback_reaction(kind, p, plain), "memory-template", persona
