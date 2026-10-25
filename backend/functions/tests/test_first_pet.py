import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.first_pet import MAX_PER_GENERATION, get_first_pet, resolve  # noqa: E402
from petlogic.register import register_device  # noqa: E402

JST = timezone(timedelta(hours=9))
T0 = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)


def put(db, pet, owner, gen, text, day):
    db.collection("pets").document(pet).collection("memories").document().set(
        {"ownerUid": owner, "generation": gen, "text": text, "createdAt": datetime(2026, 10, day, 12, tzinfo=JST)})


def setup():
    """u1 が作った PA が、u2 のもとへ(2代目)。"""
    db = FakeDb()
    a = register_device(db, "u1", "devA", T0)["petId"]
    b = register_device(db, "u2", "devB", T0)["petId"]
    db.docs[("pets", a)]["name"] = "モチ"
    report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                               "gotPetId": b, "transactionId": "t1"}, T0, run_tx=run_tx)
    return db, a, b


def test_no_pet_returns_empty():
    r = get_first_pet(FakeDb(), "nobody", T0)
    assert r["petId"] is None and r["memories"] == [] and r["appearance"] is None


def test_returns_name_generation_appearance_of_the_first_pet():
    db, a, _b = setup()
    r = get_first_pet(db, "u1", T0)
    assert r["petId"] == a and r["name"] == "モチ" and r["generation"] == 2
    assert r["withYou"] is False  # 今は u2 のもと
    assert set(r["appearance"]) >= {"stage", "primary", "secondary", "tertiary", "key"}
    assert r["stage"] == r["appearance"]["stage"]
    assert get_first_pet(db, "u2", T0)["petId"] != a  # u2 の最初のペットは、別


def test_own_memories_get_real_names_and_other_owners_memories_are_blurred():
    db, a, _b = setup()
    put(db, a, "u1", 1, "{shop_1}で{person_1}とアイスを食べた", 20)
    put(db, a, "u2", 2, "{shop_9}で遊んだ", 22)
    db.docs[("users/u1/nameMaps", a)] = {"{shop_1}": "ミスド", "{person_1}": "たろう"}
    db.docs[("users/u2/nameMaps", a)] = {"{shop_9}": "ゲーセン"}
    mem = {m["generation"]: m for m in get_first_pet(db, "u1", T0)["memories"]}
    assert mem[1]["mine"] is True and mem[1]["items"][0]["text"] == "ミスドでたろうとアイスを食べた"
    assert mem[2]["mine"] is False and mem[2]["items"][0]["text"] == "あのお店で遊んだ"
    assert "ゲーセン" not in str(mem) and "u2" not in str(mem)  # 他の飼い主の名前もUIDも出ない


def test_other_owners_names_never_leak_even_if_a_name_map_exists_for_the_viewer():
    db, a, _b = setup()
    put(db, a, "u2", 2, "{person_1}が好きだと言っていた", 22)
    db.docs[("users/u1/nameMaps", a)] = {"{person_1}": "たろう"}  # u1 自身の対応表(別の人の話)
    items = [i["text"] for m in get_first_pet(db, "u1", T0)["memories"] for i in m["items"]]
    assert items == ["あの人が好きだと言っていた"]


def test_unresolvable_placeholder_in_own_memory_is_blurred():
    assert resolve("{shop_1}へ行った", {}) == "あのお店へ行った"
    assert resolve("{shop_1}へ行った", {"{shop_1}": "ミスド"}) == "ミスドへ行った"


def test_items_are_newest_first_limited_per_generation_and_response_has_no_ids():
    db, a, _b = setup()
    for day in range(1, 16):
        put(db, a, "u1", 1, f"話{day}", day)
    items = get_first_pet(db, "u1", T0)["memories"][0]["items"]
    assert len(items) == MAX_PER_GENERATION and items[0]["text"] == "話15"
    assert set(items[0]) == {"text", "createdAt"}


def test_generations_without_memories_are_skipped_and_sorted():
    db, a, _b = setup()
    put(db, a, "u2", 3, "三代目", 22)
    put(db, a, "u1", 1, "一代目", 20)
    assert [m["generation"] for m in get_first_pet(db, "u1", T0)["memories"]] == [1, 3]
