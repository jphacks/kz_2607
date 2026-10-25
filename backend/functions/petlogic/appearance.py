"""姿(どの絵を出すか)。性格の強い2軸と、成長の段階から、絵のキーを決める。

絵そのものは、アプリ・Core2 が持つ。バックエンドは、キーだけ返す。
  tertiary    3番目に強い軸(パーツ方式で、口などを選ぶのに使える)
  key         "{一番強い軸}_{2番目の軸}_{段階}"  例: "nightowl_curious_baby"(6×5×3 = 90通り)
  fallbackKey "{一番強い軸}_{段階}"              例: "nightowl_baby"(6×3 = 18通り。キーの絵がないときの代わり)
同じ値の軸が並んだときの順番:
  ・誕生のながれで性格を決めたペット(fixed_order=True): 決まった順 activity → friendly → talkative → logical →
    curious → nightowl。birthTrait(active → affection → talkative → logic → curious → night)と同じ順なので、
    誕生のときは、birthTrait と primary が、必ず同じ軸になる。
  ・昔のペット(誕生のながれを通っていない): ペットごとに決まった順(同じペットなら、いつも同じ結果)。
種族(動物 = primary)は、誕生のながれを通ったペットでは、誕生のときの軸(birthTrait)で固定する。
交換で飼い主が変わって性格が動いても、動物は変わらない。目(secondary)と口(tertiary)は、今の性格で決まる
(動物の軸を除いた中で、強い順)。誕生のながれを通っていない昔のペットは、今の性格で決まる。
"""
import hashlib

from .register import AXIS_NAMES
from .growth import STAGES


def _tiebreak(pet_id, name):
    return hashlib.sha256(f"{pet_id}:{name}".encode()).hexdigest()


def appearance_of(pet_id, axes, stage, fixed_order=False, species=None):
    """species: 動物(primary)として固定する軸の名前(例: "nightowl")。なければ、今の性格で決める。"""
    axes = axes or {}
    tie = (lambda n: AXIS_NAMES.index(n)) if fixed_order else (lambda n: _tiebreak(pet_id, n))
    ranked = sorted(AXIS_NAMES, key=lambda n: (-float(axes.get(n, 0.5)), tie(n)))
    if species in AXIS_NAMES:
        ranked = [species] + [n for n in ranked if n != species]  # 動物は固定。目・口は、残りの中で強い順
    primary, secondary, tertiary = ranked[0], ranked[1], ranked[2]
    return {
        "stage": stage,
        "primary": primary,
        "secondary": secondary,
        "tertiary": tertiary,
        "key": f"{primary}_{secondary}_{stage}",
        "fallbackKey": f"{primary}_{stage}",
    }


def species_of(pet):
    """誕生のときに決まった、種族(動物)の軸の名前。誕生のながれを通っていないペットは None。"""
    from .talk import AI_AXIS_NAMES  # 循環を避けるため、ここで読み込む
    to_axis = {ai: mine for mine, ai in AI_AXIS_NAMES.items()}
    return to_axis.get(pet.get("birthTrait"))


def appearance_for_pet(pet_id, pet, stage):
    """ペットの見た目。種族は誕生のときの軸で固定、目・口は今の性格。"""
    return appearance_of(pet_id, pet.get("personalityAxes"), stage,
                         fixed_order=pet.get("birthAnswers") is not None, species=species_of(pet))


def all_keys():
    """用意する絵の、全キー(一覧)。"""
    keys = []
    for stage in STAGES:
        for p in AXIS_NAMES:
            keys.append(f"{p}_{stage}")
            keys.extend(f"{p}_{s}_{stage}" for s in AXIS_NAMES if s != p)
    return keys
