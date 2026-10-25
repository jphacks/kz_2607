import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.journey import (add_journey_summary, finish_journeys, start_journeys, time_of_day)  # noqa: E402
from petlogic.memory import (BATCH_TURNS, merge_facts, parse_facts, read_facts, rebuild_cache, refresh_cache, build_user_prompt, load_talk_context, parse_memories,  # noqa: E402
                             summarize_memories)
from petlogic.register import register_device  # noqa: E402
from petlogic.talk import build_ai_payload  # noqa: E402
from petlogic.talklog import claim_pending, pending_turns, read_turns, record_turn  # noqa: E402

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 24, 10, 0, tzinfo=JST)
TODAY = date(2026, 10, 24)


def reply(memories, new_names=None):
    return json.dumps({"memories": memories, "new_names": new_names or {}}, ensure_ascii=False)


def setup(turns=BATCH_TURNS):
    db = FakeDb()
    pet = register_device(db, "u1", "devA", NOW)["petId"]
    for i in range(turns):
        record_turn(db, pet, 1, f"話{i}", f"返{i}", NOW, run_tx, uid="u1")
    return db, pet


# ---- 会話の番号と取り分け ----
def test_turns_get_sequence_numbers_and_claim_is_exclusive():
    db, pet = setup(10)
    assert [t["seq"] for t in read_turns(db, pet, 1)] == list(range(1, 11))
    assert claim_pending(db, pet, 1, 10, run_tx)["turns"][-1]["seq"] == 10
    assert claim_pending(db, pet, 1, 3, run_tx) is None  # 二重には取れない
    assert pending_turns(db.docs[("pets/%s/talkLogs" % pet, "1")]) == []


def test_claim_needs_enough_turns():
    db, pet = setup(BATCH_TURNS - 1)
    assert claim_pending(db, pet, 1, BATCH_TURNS, run_tx) is None


# ---- 要約(A) ----
def test_summarize_saves_memories_names_and_cache():
    db, pet = setup()
    seen = {}

    def ai(system, user):
        seen["user"] = user
        return reply([{"text": "{shop_1}でいちごのアイスを食べた", "occurred_on": "2026-10-23"}], {"{shop_1}": "ミスド"})

    r = summarize_memories(db, pet, 1, ai, NOW, run_tx=run_tx)
    assert r == {"status": "done", "memories": 1}
    assert db.docs[("users/u1/nameMaps", pet)] == {"{shop_1}": "ミスド"}
    mem = [v for k, v in db.docs.items() if k[0] == f"pets/{pet}/memories"]
    assert mem[0]["text"] == "{shop_1}でいちごのアイスを食べた" and mem[0]["ownerUid"] == "u1"
    assert mem[0]["createdAt"].date() == date(2026, 10, 23)
    cache = db.docs[(f"pets/{pet}/memoryCache", "current")]
    assert cache["ownerUid"] == "u1" and cache["generation"] == 1 and len(cache["items"]) == 1
    assert cache["items"][0]["createdAt"].startswith("2026-10-23")
    assert "today: 2026-10-24" in seen["user"] and "飼い主: 話0" in seen["user"]


def test_not_summarized_until_batch_turns_but_force_takes_even_one_turn():
    db, pet = setup(4)
    assert summarize_memories(db, pet, 1, lambda s, u: 1 / 0, NOW, run_tx=run_tx)["status"] == "skipped"
    assert summarize_memories(db, pet, 1, lambda s, u: reply([]), NOW, force=True, run_tx=run_tx)["status"] == "done"
    db2, pet2 = setup(1)
    assert summarize_memories(db2, pet2, 1, lambda s, u: reply([]), NOW, force=True, run_tx=run_tx)["status"] == "done"
    db3, pet3 = setup(0)
    assert summarize_memories(db3, pet3, 1, lambda s, u: reply([]), NOW, force=True, run_tx=run_tx)["status"] == "skipped"


def test_failure_releases_the_claim_for_retry():
    db, pet = setup()

    def boom(s, u):
        raise RuntimeError("down")

    assert summarize_memories(db, pet, 1, boom, NOW, run_tx=run_tx)["status"] == "failed"
    assert summarize_memories(db, pet, 1, lambda s, u: reply([]), NOW, run_tx=run_tx)["status"] == "done"  # 取り戻せた


def test_bad_json_is_failure_not_crash():
    db, pet = setup()
    assert summarize_memories(db, pet, 1, lambda s, u: "これはJSONではない", NOW, run_tx=run_tx)["status"] == "failed"


def test_parse_drops_leaked_names_and_unknown_placeholders_and_normalizes_keys():
    known = {"{person_1}": "ゆうと"}
    raw = reply([
        {"text": "ゆうとと公園に行った", "occurred_on": "2026-10-23"},          # 本当の名前が残っている
        {"text": "{shop_9}でパンを食べた", "occurred_on": "2026-10-23"},         # 対応がない伏せ字
        {"text": "{shop_1}でパンを食べた", "occurred_on": "bad"},               # 日付が不正 → 今日
        {"text": "あ" * 101, "occurred_on": "2026-10-23"},                       # 長すぎる
    ], {"shop_1": "ミスド", "{person_1}": "別人", "x": "y", "{place_1}": ""})
    memories, names = parse_memories(raw, known, TODAY)
    assert names == {"{shop_1}": "ミスド"}  # 波かっこなしも直す。既知・不正・空は捨てる
    assert memories == [{"text": "{shop_1}でパンを食べた", "occurred_on": TODAY}]


def test_max_three_memories_per_run():
    items = [{"text": f"{i}番目のことをした", "occurred_on": "2026-10-23"} for i in range(6)]
    assert len(parse_memories(reply(items), {}, TODAY)[0]) == 3


def test_prompt_includes_known_names():
    p = build_user_prompt("2026-10-24", {"{shop_1}": "ミスド"}, [{"text": "a", "reply": "b"}])
    assert '"{shop_1}": "ミスド"' in p and "飼い主: a" in p and "ペット: b" in p


# ---- 会話に付ける材料(C) ----
def test_talk_context_only_for_current_owner_and_generation():
    db, pet = setup()
    summarize_memories(db, pet, 1, lambda s, u: reply([{"text": "散歩をした", "occurred_on": "2026-10-23"}]), NOW, run_tx=run_tx)
    pet_doc = db.docs[("pets", pet)]
    ctx = load_talk_context(db, "u1", pet, pet_doc)
    assert [m["text"] for m in ctx["memories"]] == ["散歩をした"]
    assert load_talk_context(db, "u2", pet, pet_doc)["memories"] == []  # 別の飼い主には渡さない
    changed = load_talk_context(db, "u2", pet, {**pet_doc, "generation": 2})  # 別の飼い主に代わった
    assert changed["memories"] == [] and [m["text"] for m in changed["pastMemories"]] == ["散歩をした"]


def test_payload_adds_only_non_empty_context():
    pet = {"generation": 3, "name": "モチ"}
    assert "memories" not in build_ai_payload("x", "p", pet, NOW, {"memories": [], "nameMap": {}, "journeys": []})
    p = build_ai_payload("x", "p", pet, NOW, {"memories": [{"id": "m", "text": "t", "createdAt": "c"}],
                                              "nameMap": {"{shop_1}": "ミスド"}, "journeys": [{"generation": 1}]})
    assert p["generation"] == 3 and p["memories"][0]["id"] == "m" and p["nameMap"] == {"{shop_1}": "ミスド"}
    assert p["journeys"] == [{"generation": 1}]


# ---- 旅の記録(B) ----
def exchange(db, a, b):
    return report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                                      "gotPetId": b, "transactionId": "t1"}, NOW, run_tx=run_tx)["handoffId"]


def setup_exchange(turns=10):
    db, a = setup(turns)
    b = register_device(db, "u2", "devB", NOW)["petId"]
    db.docs[("pets", a)]["points"] = 3.0
    db.docs[("pets/%s/history" % a, "h1")] = {"type": "wordsTaught", "words": ["めっちゃ", "おつかれ", "やばい"],
                                              "generation": 1}
    db.docs[("pets/%s/history" % a, "h2")] = {"type": "wordsTaught", "words": ["だいすき"], "generation": 2}
    return db, a, b, exchange(db, a, b)


def test_exchange_records_talk_counts_and_journey_status():
    db, a, b, h = setup_exchange()
    handoff = db.docs[("handoffs", h)]
    assert handoff["journeyStatus"] == "pending" and handoff["endedTalkCounts"] == {a: 3, b: 0}


def test_values_written_first_without_ai():
    db, a, b, h = setup_exchange()
    assert start_journeys(db, h, run_tx)["status"] == "values"
    entry = db.docs[("pets", a)]["journeys"][0]
    assert entry == {"generation": 1, "learnedWords": ["めっちゃ", "おつかれ"], "talkCount": 3, "timeOfDay": "朝"}
    assert db.docs[(f"pets/{a}/journeys", "1")] == entry
    assert start_journeys(db, h, run_tx)["status"] == "skipped"  # 二重には動かない


def test_time_of_day_buckets():
    def at(hour):
        return {"at": datetime(2026, 10, 24, hour, tzinfo=JST)}
    assert time_of_day([at(6), at(7), at(22)]) == "朝"
    assert time_of_day([at(18)]) == "夕方" and time_of_day([at(23), at(2)]) == "夜" and time_of_day([]) is None


def test_summary_is_added_from_memories_of_that_generation():
    db, a, b, h = setup_exchange()
    summarize_memories(db, a, 1, lambda s, u: reply([{"text": "{place_1}でよく散歩した", "occurred_on": "2026-10-23"}],
                                                    {"{place_1}": "中央公園"}), NOW, run_tx=run_tx)
    start_journeys(db, h, run_tx)
    r = finish_journeys(db, h, lambda s, u: json.dumps({"summary": "{place_1}でよく散歩した"}, ensure_ascii=False)
                        if "思い出の一覧" in u else reply([]), NOW, run_tx)
    assert r["status"] == "done"
    journey = db.docs[("pets", a)]["journeys"][0]
    assert journey["summary"] == "{place_1}でよく散歩した" and journey["talkCount"] == 3
    assert db.docs[("handoffs", h)]["journeyStatus"] == "done"


def test_summary_with_real_name_is_rejected():
    db, a, b, h = setup_exchange()
    summarize_memories(db, a, 1, lambda s, u: reply([{"text": "{place_1}でよく散歩した", "occurred_on": "2026-10-23"}],
                                                    {"{place_1}": "中央公園"}), NOW, run_tx=run_tx)
    start_journeys(db, h, run_tx)
    r = add_journey_summary(db, a, 1, lambda s, u: json.dumps({"summary": "中央公園でよく散歩した"}, ensure_ascii=False))
    assert r["status"] == "rejected" and "summary" not in db.docs[("pets", a)]["journeys"][0]


def test_no_memories_means_no_summary_and_ai_failure_marks_failed():
    db, a, b, h = setup_exchange(turns=0)
    start_journeys(db, h, run_tx)
    assert finish_journeys(db, h, lambda s, u: 1 / 0, NOW, run_tx)["status"] == "done"  # 会話なし → AIは呼ばない
    db2, a2, b2, h2 = setup_exchange(turns=5)
    start_journeys(db2, h2, run_tx)

    def boom(s, u):
        raise RuntimeError("down")

    assert finish_journeys(db2, h2, boom, NOW, run_tx)["status"] == "failed"
    assert db2.docs[("pets", a2)]["journeys"][0]["talkCount"] == 3  # 値は、書けている


def test_batch_turns_is_configurable():
    db, pet = setup(5)
    db.collection("config").document("game").set({"summarizeEveryTurns": 10})
    assert summarize_memories(db, pet, 1, lambda s, u: 1 / 0, NOW, run_tx=run_tx)["status"] == "skipped"


# ---- 前の代の思い出(pastMemories) ----
def put_memory(db, pet, owner, gen, text, day):
    db.collection("pets").document(pet).collection("memories").document().set(
        {"ownerUid": owner, "generation": gen, "text": text,
         "createdAt": datetime(2026, 10, day, 12, tzinfo=JST)})


def test_past_items_are_blurred_limited_and_split_near_and_first():
    db, pet = setup(0)
    for d in range(1, 11):
        put_memory(db, pet, "uA", 1, f"{{shop_1}}で{d}番目をした", d)
    for d in range(1, 11):
        put_memory(db, pet, "uB", 2, f"{{person_1}}と{d}番目をした", d)
    put_memory(db, pet, "uC", 3, "いまの人のこと", 20)
    rebuild_cache(db, pet, "uC", 4, NOW)  # 4代目: 直前=3(uC自身→外す)ではなく、uCは3代目を育てた人
    cache = db.docs[(f"pets/{pet}/memoryCache", "current")]
    assert [m["text"] for m in cache["items"]] == ["いまの人のこと"]
    gens = [m["generation"] for m in cache["pastItems"]]
    assert gens.count(2) == 0 and gens.count(1) == 3  # 直前(3代目)は本人なので無し。1代目から3件
    rebuild_cache(db, pet, "uD", 3, NOW)  # 3代目の飼い主が別人なら: 直前=2代目から7件+1代目から3件
    past = db.docs[(f"pets/{pet}/memoryCache", "current")]["pastItems"]
    assert [m["generation"] for m in past] == [2] * 7 + [1] * 3
    assert past[0]["text"] == "あの人と10番目をした" and past[7]["text"].startswith("あのお店で")
    assert all("{" not in m["text"] and {"id", "createdAt"} <= set(m) for m in past)
    assert past[0]["createdAt"].startswith("2026-10-10")


def test_second_generation_takes_ten_from_first():
    db, pet = setup(0)
    for d in range(1, 13):
        put_memory(db, pet, "uA", 1, f"{d}番目をした", d)
    rebuild_cache(db, pet, "uB", 2, NOW)
    assert len(db.docs[(f"pets/{pet}/memoryCache", "current")]["pastItems"]) == 10


def test_returning_owner_gets_old_memories_as_own_and_not_as_past():
    db, pet = setup(0)
    put_memory(db, pet, "uA", 1, "{shop_1}で遊んだ", 1)
    put_memory(db, pet, "uB", 2, "べつの人のこと", 2)
    rebuild_cache(db, pet, "uA", 3, NOW)
    cache = db.docs[(f"pets/{pet}/memoryCache", "current")]
    assert [m["text"] for m in cache["items"]] == ["{shop_1}で遊んだ"]  # 本人の分は伏せ字のまま(nameMapは本人の分)
    assert [m["text"] for m in cache["pastItems"]] == ["べつの人のこと"]


def test_talk_context_includes_past_memories_and_payload_passes_them():
    db, pet = setup(0)
    put_memory(db, pet, "uA", 1, "{shop_1}で遊んだ", 1)
    rebuild_cache(db, pet, "u1", 2, NOW)
    ctx = load_talk_context(db, "u1", pet, {"generation": 2})
    assert ctx["pastMemories"][0]["text"] == "あのお店で遊んだ"
    assert build_ai_payload("x", "p", {"generation": 2}, NOW, ctx)["pastMemories"][0]["generation"] == 1


def test_summary_finishing_after_the_exchange_still_reaches_the_new_owners_cache():
    db, pet = setup(5)
    db.docs[("pets", pet)].update({"generation": 2, "ownerUid": "u2"})  # 要約の途中で、交換が済んだ(別の飼い主・2代目)
    refresh_cache(db, pet, NOW)  # 交換の裏の処理が、先に空の置き場を作った
    assert db.docs[(f"pets/{pet}/memoryCache", "current")]["pastItems"] == []
    summarize_memories(db, pet, 1, lambda s, u: reply([{"text": "散歩をした", "occurred_on": "2026-10-23"}]),
                       NOW, force=True, run_tx=run_tx)
    cache = db.docs[(f"pets/{pet}/memoryCache", "current")]
    assert cache["ownerUid"] == "u2" and cache["generation"] == 2  # 古い飼い主用に戻らない
    assert [m["text"] for m in cache["pastItems"]] == ["散歩をした"]  # 取りこぼさない


def test_talk_context_reads_memories_even_before_the_new_owners_cache_exists():
    db, pet = setup(0)
    put_memory(db, pet, "uA", 1, "{shop_1}でアイスを食べた", 1)
    db.docs[(f"pets/{pet}/memoryCache", "current")] = {"ownerUid": "uA", "generation": 1, "items": [], "pastItems": []}  # 古い置き場
    ctx = load_talk_context(db, "uB", pet, {"generation": 2})
    assert ctx["memories"] == [] and [m["text"] for m in ctx["pastMemories"]] == ["あのお店でアイスを食べた"]
    assert db.docs[(f"pets/{pet}/memoryCache", "current")]["ownerUid"] == "uA"  # 読むだけで、書かない
    ctx2 = load_talk_context(db, "uA", pet, {"generation": 3})  # 元の飼い主に戻ったら、昔の分が自分の思い出に
    assert [m["text"] for m in ctx2["memories"]] == ["{shop_1}でアイスを食べた"] and ctx2["pastMemories"] == []


# ---- 大事な事実(facts) ----
def reply_facts(facts, memories=None, new_names=None):
    return json.dumps({"memories": memories or [], "new_names": new_names or {}, "facts": facts}, ensure_ascii=False)


NAMES = {"{person_1}": "たろう", "{food_1}": "ミスドのドーナツ"}


def test_parse_facts_accepts_valid_owner_name_and_likes():
    raw = reply_facts({"ownerName": "{person_1}", "likes": ["いちごのアイス", "犬", "海", "四つ目"]})
    assert parse_facts(raw, NAMES) == {"ownerName": "{person_1}", "likes": ["いちごのアイス", "犬", "海"]}


@pytest.mark.parametrize("facts,expected", [
    ({"ownerName": "たろう"}, {}),  # 伏せ字になっていない
    ({"ownerName": "{person_9}"}, {}),  # 対応する名前がない
    ({"ownerName": "{shop_1}"}, {}),  # person 以外
    ({"ownerName": None, "likes": []}, {}),
    ({"likes": ["たろうの家"]}, {}),  # 本当の名前が残っている
    ({"likes": ["{food_9}"]}, {}),  # 解決できない伏せ字
    ({"likes": ["あ" * 21, "", 5]}, {}),  # 長すぎる・空・文字でない
    ({"likes": "アイス"}, {}),  # 配列でない
    ({"likes": ["{food_1}"]}, {"likes": ["{food_1}"]}),  # 解決できる伏せ字はそのまま
    ("facts", {}),
])
def test_parse_facts_drops_bad_values(facts, expected):
    assert parse_facts(reply_facts(facts), NAMES) == expected


def test_parse_facts_without_facts_or_bad_json_is_empty():
    assert parse_facts(reply([]), NAMES) == {}
    assert parse_facts("これはJSONではない", NAMES) == {}


def test_merge_facts_overwrites_owner_name_and_keeps_newest_three_likes():
    old = {"ownerName": "{person_1}", "likes": ["A", "B", "C"]}
    assert merge_facts(old, {"ownerName": "{person_2}", "likes": ["D"]}) == {"ownerName": "{person_2}", "likes": ["B", "C", "D"]}
    assert merge_facts(old, {"likes": ["B"]}) == {"ownerName": "{person_1}", "likes": ["A", "C", "B"]}  # 同じものは新しい方へ
    assert merge_facts({}, {}) == {}


def test_summarize_saves_facts_separately_and_puts_them_in_cache_and_context():
    db, pet = setup()
    summarize_memories(db, pet, 1, lambda s, u: reply_facts(
        {"ownerName": "{person_1}", "likes": ["いちごのアイス"]}, [], {"{person_1}": "たろう"}), NOW, run_tx=run_tx)
    saved = db.docs[("users/u1/petFacts", pet)]
    assert saved["ownerName"] == "{person_1}" and saved["likes"] == ["いちごのアイス"]  # 思い出が無い回でも残る
    assert db.docs[(f"pets/{pet}/memoryCache", "current")]["facts"] == {"ownerName": "{person_1}", "likes": ["いちごのアイス"]}
    ctx = load_talk_context(db, "u1", pet, db.docs[("pets", pet)])
    assert ctx["facts"] == {"ownerName": "{person_1}", "likes": ["いちごのアイス"]}
    assert build_ai_payload("x", pet, {"generation": 1}, NOW, ctx)["facts"]["ownerName"] == "{person_1}"


def test_facts_accumulate_across_summaries():
    db, pet = setup()
    summarize_memories(db, pet, 1, lambda s, u: reply_facts({"ownerName": "{person_1}", "likes": ["A"]}, [], {"{person_1}": "たろう"}),
                       NOW, run_tx=run_tx)
    for i in range(BATCH_TURNS):
        record_turn(db, pet, 1, f"続き{i}", f"返{i}", NOW, run_tx, uid="u1")
    summarize_memories(db, pet, 1, lambda s, u: reply_facts({"ownerName": None, "likes": ["B"]}), NOW, run_tx=run_tx)
    assert read_facts(db, "u1", pet) == {"ownerName": "{person_1}", "likes": ["A", "B"]}


def test_facts_are_not_given_to_the_next_owner_but_return_with_the_old_one():
    db, pet = setup()
    summarize_memories(db, pet, 1, lambda s, u: reply_facts({"ownerName": "{person_1}", "likes": ["A"]}, [], {"{person_1}": "たろう"}),
                       NOW, run_tx=run_tx)
    pet_doc = db.docs[("pets", pet)]
    assert load_talk_context(db, "u2", pet, {**pet_doc, "generation": 2})["facts"] == {}
    rebuild_cache(db, pet, "u2", 2, NOW)
    assert db.docs[(f"pets/{pet}/memoryCache", "current")]["facts"] == {}
    rebuild_cache(db, pet, "u1", 1, NOW)
    assert db.docs[(f"pets/{pet}/memoryCache", "current")]["facts"]["ownerName"] == "{person_1}"


def test_talk_context_reads_facts_when_old_cache_has_no_facts_key():
    db, pet = setup()
    db.docs[("users/u1/petFacts", pet)] = {"ownerName": "{person_1}", "likes": ["A"]}
    db.docs[(f"pets/{pet}/memoryCache", "current")] = {"ownerUid": "u1", "generation": 1, "items": [], "pastItems": []}
    assert load_talk_context(db, "u1", pet, db.docs[("pets", pet)])["facts"]["likes"] == ["A"]


def test_payload_omits_empty_facts():
    assert "facts" not in build_ai_payload("x", "p", {"generation": 1}, NOW, {"facts": {}})
