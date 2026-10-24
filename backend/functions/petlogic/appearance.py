"""姿(どの絵を出すか)。性格の強い2軸と、成長の段階から、絵のキーを決める。

絵そのものは、アプリ・Core2 が持つ。バックエンドは、キーだけ返す。
  key         "{一番強い軸}_{2番目の軸}_{段階}"  例: "nightowl_curious_baby"(6×5×3 = 90通り)
  fallbackKey "{一番強い軸}_{段階}"              例: "nightowl_baby"(6×3 = 18通り。キーの絵がないときの代わり)
同じ値の軸が並んだときは、ペットごとに決まった順で選ぶ(同じペットなら、いつも同じ結果)。
"""
import hashlib

from .register import AXIS_NAMES
from .growth import STAGES


def _tiebreak(pet_id, name):
    return hashlib.sha256(f"{pet_id}:{name}".encode()).hexdigest()


def appearance_of(pet_id, axes, stage):
    axes = axes or {}
    ranked = sorted(AXIS_NAMES, key=lambda n: (-float(axes.get(n, 0.5)), _tiebreak(pet_id, n)))
    primary, secondary = ranked[0], ranked[1]
    return {
        "stage": stage,
        "primary": primary,
        "secondary": secondary,
        "key": f"{primary}_{secondary}_{stage}",
        "fallbackKey": f"{primary}_{stage}",
    }


def all_keys():
    """用意する絵の、全キー(一覧)。"""
    keys = []
    for stage in STAGES:
        for p in AXIS_NAMES:
            keys.append(f"{p}_{stage}")
            keys.extend(f"{p}_{s}_{stage}" for s in AXIS_NAMES if s != p)
    return keys
