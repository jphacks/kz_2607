"""姿(どの絵を出すか)。性格の強い2軸と、成長の段階から、絵のキーを決める。

絵そのものは、アプリ・Core2 が持つ。バックエンドは、キーだけ返す。
  key         "{一番強い軸}_{2番目の軸}_{段階}"  例: "nightowl_curious_baby"(6×5×3 = 90通り)
  fallbackKey "{一番強い軸}_{段階}"              例: "nightowl_baby"(6×3 = 18通り。キーの絵がないときの代わり)
同じ値の軸が並んだときの順番:
  ・誕生のながれで性格を決めたペット(fixed_order=True): 決まった順 activity → friendly → talkative → logical →
    curious → nightowl。birthTrait(active → affection → talkative → logic → curious → night)と同じ順なので、
    誕生のときは、birthTrait と primary が、必ず同じ軸になる。
  ・昔のペット(誕生のながれを通っていない): ペットごとに決まった順(同じペットなら、いつも同じ結果)。
"""
import hashlib

from .register import AXIS_NAMES
from .growth import STAGES


def _tiebreak(pet_id, name):
    return hashlib.sha256(f"{pet_id}:{name}".encode()).hexdigest()


def appearance_of(pet_id, axes, stage, fixed_order=False):
    axes = axes or {}
    tie = (lambda n: AXIS_NAMES.index(n)) if fixed_order else (lambda n: _tiebreak(pet_id, n))
    ranked = sorted(AXIS_NAMES, key=lambda n: (-float(axes.get(n, 0.5)), tie(n)))
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
