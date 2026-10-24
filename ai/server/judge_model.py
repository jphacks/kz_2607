"""
judge_model.py — 判定モデル（自作 Transformer 3つの平均＋NGワード）

中身は judge_infer.py の PetJudgeRunner。ここでは重みを探して読み込み、空打ちするだけ。
    judge = JudgeModel()
    j = judge(turns)   # turns = [{"speaker": "owner"|"pet", "text": ...}, ...]
    j["action"]        # 雑談・込み入った質問・思い出・ペット自身・安全な返事
"""
import os
from pathlib import Path
from typing import List

from common import HERE
from judge_infer import PetJudgeRunner


def find_ckpts() -> List[str]:
    """判定モデルの重み judge/v9*/best.pt を、このファイルから上へ3階層まで探す。JUDGE_CKPTS があればそれを使う。"""
    if os.environ.get("JUDGE_CKPTS"):
        return os.environ["JUDGE_CKPTS"].split()
    for base in [HERE, *HERE.parents[:3]]:
        cands = [base / "judge" / d / "best.pt" for d in ("v9", "v9_s1", "v9_s2")]
        if all(c.exists() for c in cands):
            return [str(c) for c in cands]
    return [str(HERE.parent / "judge" / d / "best.pt") for d in ("v9", "v9_s1", "v9_s2")]


class JudgeModel:
    def __init__(self, ckpts: List[str] = None):
        self.ckpts = ckpts or find_ckpts()
        self.runner = PetJudgeRunner(self.ckpts)
        self.runner([{"speaker": "owner", "text": "こんにちは"}])   # 空打ち

    def __call__(self, turns: List[dict]) -> dict:
        return self.runner(turns)
