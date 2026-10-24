"""
chat_lora.py — 雑談：性格LoRA の LFM2.5（llama-server 8081・評価名 t04b）

学習と同じ system プロンプト（teacher_data.py）で、上位3軸の LoRA を s=1.5 で混ぜて返す。
赤ちゃんの段階は、子どもの段階で作ってから赤ちゃん言葉に直す（baby_talk.py）。
    chat = ChatLoRA()
    chat.load()            # 載っている LoRA の番号を調べる。使えなければ False
    reply, persona = chat.reply(profile, hist, user_text)
    # system の最後に文を足す・温度などを変える（ペット自身・思い出で使う）
    reply, persona = chat.reply(profile, hist, user_text, extra="【あなた自身のこと】…", sampling={"temperature": 0.3})
    # extra を先頭に置く・手本の会話（few-shot）を前に入れる・モデルに見せる発言だけ変える
    reply, persona = chat.reply(profile, hist, user_text, extra=..., extra_first=True,
                                shots=[{"speaker": "owner", "text": …}, {"speaker": "pet", "text": …}],
                                model_text="名前なに？（名前を答える）")
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from common import (AXIS_ORDER, TEACHER_DIR, TEACHER_ERR, PetProfile, build_system_prompt, clean_reply, cut,
                    fix_reading, hour_to_label, to_baby, top_axes)

CHAT_LLAMA = os.environ.get("CHAT_LLAMA", "http://127.0.0.1:8081").rstrip("/")
TOPK = int(os.environ.get("LORA_TOPK", "3"))
SCALE = float(os.environ.get("LORA_SCALE", "1.5"))
SAMPLING = {"temperature": 0.4, "top_p": 0.9, "min_p": 0.1, "repeat_penalty": 1.1}
MAX_TOKENS = 100
N_HIST = 4            # 学習データと同じ：直前4発言＋今の発言


class ChatLoRA:
    def __init__(self, url: str = CHAT_LLAMA, topk: int = TOPK, scale: float = SCALE):
        self.url, self.topk, self.scale = url, topk, scale
        self.lora_ids: Dict[str, int] = {}    # 軸 → llama-server の LoRA 番号。空なら使えない
        self.status = "未確認"

    @property
    def ready(self) -> bool:
        return bool(self.lora_ids)

    def load(self) -> bool:
        """8081 に載っている性格LoRA の番号を、ファイル名 axis_<軸>.gguf から調べる。"""
        if self.url.lower() == "off":
            self.status = "使わない（CHAT_LLAMA=off）"
            return False
        if TEACHER_ERR:
            self.status = f"使わない（teacher_data.py / baby_talk.py が読めない: {TEACHER_ERR}）"
            return False
        try:
            js = requests.get(f"{self.url}/lora-adapters", timeout=5).json()
            ids = {}
            for a in js:
                m = re.search(r"axis_(\w+?)(?:[._-][\w.-]*)?\.gguf", Path(a.get("path", "")).name)
                if m and m.group(1) in AXIS_ORDER:
                    ids[m.group(1)] = a["id"]
            self.lora_ids = ids
            missing = [a for a in AXIS_ORDER if a not in ids]
            self.status = f"ok  LoRA: {ids}  teacher: {TEACHER_DIR}" + (f"  ※ 足りない: {missing}" if missing else "")
        except Exception as e:
            self.lora_ids = {}
            self.status = f"NG — 雑談も 8080 で返す: {e}"
        return self.ready

    def scales(self, axes: Dict[str, float]) -> Dict[str, float]:
        """上位K軸に s × q_i、残りに 0。v がすべて0なら性格LoRA なし。"""
        top = top_axes(axes, self.topk)
        total = sum(axes[a] for a in top)
        if total <= 0:
            return {a: 0.0 for a in AXIS_ORDER}
        return {a: (self.scale * axes[a] / total if a in top else 0.0) for a in AXIS_ORDER}

    @staticmethod
    def messages(system: str, hist: List[dict], user_text: str, pet: str,
                 shots: Optional[List[dict]] = None) -> List[dict]:
        """学習データと同じ形：system ＋（手本の会話）＋ 直前4発言（飼い主の発言から始める）＋ 今の発言。
        手本の会話は直前4発言の数に入れない（切り落とされないように）。"""
        h = hist[-N_HIST:]
        while h and h[0]["speaker"] not in ("owner", "飼い主"):
            h = h[1:]
        msgs = [{"role": "system", "content": system}]
        for x in list(shots or []) + h:
            if x["speaker"] in ("owner", "飼い主"):
                msgs.append({"role": "user", "content": x["text"]})
            else:
                msgs.append({"role": "assistant", "content": clean_reply(x["text"], pet)})
        msgs.append({"role": "user", "content": user_text})
        return msgs

    def reply(self, p: PetProfile, hist: List[dict], user_text: str,
              extra: str = "", sampling: Optional[dict] = None, extra_first: bool = False,
              shots: Optional[List[dict]] = None, model_text: Optional[str] = None) -> Tuple[str, dict]:
        """extra: system に足す文（プロフィール・答え方の決まり）。extra_first なら先頭、ふだんは最後。
        sampling: SAMPLING の上書き。shots: 直前の会話の前に入れる手本の会話。
        model_text: モデルに見せる今の発言（ヒントを付けたもの）。無ければ user_text。
        persona["raw"] は赤ちゃん言葉に直す前・2文で切る前の返事（事実のチェックに使う）。"""
        scales = self.scales(p.axes)
        ending = p.ending
        gen_stage = 2 if p.stage == 1 else p.stage          # 赤ちゃんは子どもの段階で作ってから直す
        system = build_system_prompt(p.name, gen_stage, ending, hour_to_label(p.hour), p.owner_style, p.first_person)
        if extra:
            system = (extra.strip() + "\n\n" + system.strip()) if extra_first else (system.rstrip() + "\n\n" + extra.strip())
        samp = {**SAMPLING, **(sampling or {})}
        body = {"messages": self.messages(system, hist, model_text or user_text, p.name, shots), "max_tokens": MAX_TOKENS,
                "stream": False, **samp,
                "lora": [{"id": self.lora_ids[a], "scale": round(scales.get(a, 0.0), 3)}
                         for a in AXIS_ORDER if a in self.lora_ids]}
        r = requests.post(f"{self.url}/v1/chat/completions", json=body, timeout=60)
        r.raise_for_status()
        raw = clean_reply((r.json()["choices"][0]["message"]["content"] or "").strip(), p.name)
        reply = to_baby(fix_reading(raw), ending) if p.stage == 1 else cut(raw, 2)
        persona = {"scales": {a: round(x, 2) for a, x in scales.items() if x > 0}, "stage": p.stage,
                   "ending": ending, "hour": p.hour, "raw": raw,
                   "temperature": samp["temperature"], "extra": bool(extra), "shots": len(shots or [])}
        return reply, persona