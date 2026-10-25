"""最初のペットの紹介。ログインしているユーザーが一番最初に作ったペットの、名前・今の世代・見た目・世代別の思い出。

  自分が育てた代の思い出: 本当の名前に戻して返す(自分の nameMap で)。
  ほかの飼い主が育てた代の思い出: 公開できる形だけ返す。人・お店などの名前は「あの人」「あのお店」にぼかし、
  飼い主のUID・思い出のIDは返さない。
"""
import re
from datetime import datetime, timezone

from .appearance import appearance_of
from .growth import stage_config, stage_of
from .memory import ANY_PLACEHOLDER, blur, read_memories, read_name_map
from .users import ensure_first_pet_quietly, oldest_created_pet

MAX_PER_GENERATION = 10  # 1つの代につき、新しい順に、この件数まで


def resolve(text, name_map):
    """自分の思い出の伏せ字を、本当の名前に戻す。対応する名前がないものは、ぼかす。"""
    def one(m):
        real = name_map.get(m.group(0))
        return real if real else blur(m.group(0))
    return ANY_PLACEHOLDER.sub(one, text)


def _day(d):
    created = d.get("createdAt")
    return created.isoformat() if hasattr(created, "isoformat") else None


def get_first_pet(db, uid, now=None):
    """返す: {"petId": なければ null, "name", "generation", "stage", "appearance", "withYou", "memories": [...]}

    memories は、代の小さい順: [{"generation", "mine"(その代は自分が育てた), "items": [{"text", "createdAt"}]}]
    items は新しい順で、1つの代につき最大10件。思い出のない代は含めない。
    """
    pet_id = ensure_first_pet_quietly(db, uid, now or datetime.now(timezone.utc)) or oldest_created_pet(db, uid)
    if pet_id is None:
        return {"petId": None, "name": None, "generation": None, "stage": None, "appearance": None,
                "withYou": False, "memories": []}
    snap = db.collection("pets").document(pet_id).get()
    if not snap.exists:
        return {"petId": None, "name": None, "generation": None, "stage": None, "appearance": None,
                "withYou": False, "memories": []}
    pet = snap.to_dict()
    stage = stage_of(pet.get("totalTalks", 0), *stage_config(db))["stage"]
    name_map = read_name_map(db, uid, pet_id)

    by_generation = {}
    for _id, d in read_memories(db, pet_id):
        text = d.get("text")
        if not isinstance(text, str) or not isinstance(d.get("generation"), int):
            continue
        mine = d.get("ownerUid") == uid
        by_generation.setdefault(d["generation"], []).append(
            (d.get("createdAt"), mine, resolve(text, name_map) if mine else blur(text), _day(d)))

    memories = []
    for generation in sorted(by_generation):
        rows = sorted(by_generation[generation], key=lambda r: r[0].timestamp() if hasattr(r[0], "timestamp") else 0,
                      reverse=True)
        memories.append({
            "generation": generation,
            "mine": any(r[1] for r in rows),
            "items": [{"text": r[2], "createdAt": r[3]} for r in rows[:MAX_PER_GENERATION]],
        })

    return {
        "petId": pet_id,
        "name": pet.get("name"),
        "generation": pet.get("generation", 1),
        "stage": stage,
        "appearance": appearance_of(pet_id, pet.get("personalityAxes"), stage,
                                    fixed_order=pet.get("birthAnswers") is not None),
        "withYou": pet.get("ownerUid") == uid,
        "memories": memories,
    }
