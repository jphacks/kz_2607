import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.birth import birth_status_of, birth_trait, parse_answers, set_initial_personality  # noqa: E402
from petlogic.birth_profile import generate_birth_profile, parse_profile  # noqa: E402
from petlogic.naming import set_pet_name  # noqa: E402
from petlogic.pet import get_pet  # noqa: E402
from petlogic.talk import build_ai_payload  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.register import register_device  # noqa: E402

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


def setup():
    db = FakeDb()
    a = register_device(db, "u1", "devA", NOW)["petId"]
    b = register_device(db, "u2", "devB", NOW)["petId"]
    return db, a, b


def call(db, uid="u1", dev="devA", answers=(0, 1, 2, 3, 3, 0), version=1, **extra):
    return set_initial_personality(db, uid, {"deviceId": dev, "answers": answers if isinstance(answers, dict) else list(answers),
                                             "questionnaireVersion": version, **extra}, NOW, run_tx)


def err(fn):
    with pytest.raises(ApiError) as e:
        fn()
    return e.value


def test_sets_axes_base_trait_and_appearance_on_server():
    db, a, _ = setup()
    r = call(db, axes={"activity": 0.99})  # アプリの値は使わない
    assert r["personalityAxes"] == {"activity": 0.2, "friendly": 0.4, "talkative": 0.6, "logical": 0.8,
                                    "curious": 0.8, "nightowl": 0.2}
    assert r["birthTrait"] == "logic"  # logical と curious が同じ値 → logical が先
    assert r["alreadySet"] is False and r["appearance"]["key"].endswith("_baby")
    pet = db.docs[("pets", a)]
    assert pet["axesBase"] == pet["personalityAxes"] == r["personalityAxes"]
    assert pet["birthAnswers"] == [0, 1, 2, 3, 3, 0] and pet["questionnaireVersion"] == 1


def test_trait_tie_order():
    assert birth_trait({n: 0.4 for n in ("activity", "friendly", "talkative", "logical", "curious", "nightowl")}) == "active"
    assert birth_trait({"activity": 0.2, "friendly": 0.2, "talkative": 0.2, "logical": 0.2, "curious": 0.2,
                        "nightowl": 0.8}) == "night"


def test_same_answers_again_is_ok_but_different_is_rejected():
    db, a, _ = setup()
    call(db)
    assert call(db)["alreadySet"] is True
    assert err(lambda: call(db, answers=(3, 3, 3, 3, 3, 3))).reason == "personality_already_set"
    assert err(lambda: call(db, version=2)).reason == "personality_already_set"
    assert db.docs[("pets", a)]["birthAnswers"] == [0, 1, 2, 3, 3, 0]


def test_validation():
    for bad in ([0, 1, 2], [0, 1, 2, 3, 3, 4], [0, 1, 2, 3, 3, -1], [0, 1, 2, 3, 3, 1.5], [True] * 6, "abc", None):
        assert err(lambda: parse_answers(bad)).code == "invalid-argument"
    assert parse_answers({"activity": 3, "friendly": 2, "talkative": 1, "logical": 0, "curious": 0, "nightowl": 1}) \
        == [3, 2, 1, 0, 0, 1]
    db, _, _ = setup()
    assert err(lambda: call(db, version=0)).code == "invalid-argument"
    assert err(lambda: call(db, version="bad version!")).code == "invalid-argument"
    assert call(db, version="birth_v1_6q4")["status"] == "ok"  # 文字列のバージョンもよい


def test_only_creator_who_still_owns_first_generation_before_talking():
    db, a, b = setup()
    assert err(lambda: call(db, uid="u2")).code == "permission-denied"  # 他人の端末
    db.docs[("pets", a)]["totalTalks"] = 1
    assert err(lambda: call(db)).code == "failed-precondition"  # もう話した
    db.docs[("pets", a)]["totalTalks"] = 0
    report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a, "gotPetId": b,
                               "transactionId": "t1"}, NOW, run_tx=run_tx)
    assert err(lambda: call(db, dev="devA")).reason == "not_creator"  # 交換のあと、手元にいるのは他人が作ったペット
    db.docs[("pets", a)].update({"ownerUid": "u2", "generation": 2})
    db.docs[("devices", "devA")]["currentPetId"] = a  # 作った本人の端末に戻っても、2代目以降は決められない
    assert err(lambda: call(db, dev="devA")).reason == "personality_not_allowed"


# ---- 誕生の進み具合と、誕生プロフィール ----
GOOD = ('{"nameCandidates": ["モチ", "ポポ", "ルル"], "description": "元気な子。", "firstPerson": "ぼく",'
        ' "speechNote": "元気な話し方。", "firstWords": "はじめまして！"}')


def gen(db, ai, uid="u1", pet=None, **kw):
    return generate_birth_profile(db, uid, {"petId": pet, **kw}, NOW, ai, run_tx)


def test_new_pet_is_egg_and_legacy_status_is_inferred():
    db, a, _ = setup()
    assert db.docs[("pets", a)]["birthStatus"] == "egg" and get_pet(db, "u1", "devA")["birthStatus"] == "egg"
    assert birth_status_of({"creatorUid": "u", "ownerUid": "u"}) == "egg"  # 値がなくても、中身が空なら egg
    assert birth_status_of({"name": "モチ"}) == "born"
    assert birth_status_of({"totalTalks": 3}) == "born" and birth_status_of({"generation": 2}) == "born"
    assert birth_status_of({"creatorUid": "a", "ownerUid": "b"}) == "born"
    assert birth_status_of({"birthAnswers": [0] * 6}) == "personality_set"
    assert birth_status_of({"birthAnswers": [0] * 6, "birthProfile": {"x": 1}}) == "profile_ready"


def test_full_flow_status_changes_and_getpet_restores():
    db, a, _ = setup()
    r = call(db, requestId="11111111-2222-4333-8444-555555555555", version="birth_v1_6q4")
    assert r["birthStatus"] == "personality_set"
    assert db.docs[("pets", a)]["birthRequestId"].startswith("1111")
    g = gen(db, lambda s, u: GOOD, pet=a)
    assert g["source"] == "ai" and g["birthStatus"] == "profile_ready" and g["nameCandidates"] == ["モチ", "ポポ", "ルル"]
    pet = get_pet(db, "u1", "devA")
    assert pet["birthStatus"] == "profile_ready" and pet["birthProfile"]["firstPerson"] == "ぼく"
    assert pet["birthTrait"] == r["birthTrait"] and pet["firstPerson"] is None
    n = set_pet_name(db, "u1", {"deviceId": "devA", "name": "モチ"}, run_tx)
    assert n["birthStatus"] == "born" and n["firstPerson"] == "ぼく" and n["firstWords"] == "はじめまして！"
    assert n["alreadyBorn"] is False
    again = set_pet_name(db, "u1", {"deviceId": "devA", "name": "モチ"}, run_tx)
    assert again["alreadyBorn"] is True and again["firstWords"] == "はじめまして！"
    assert err(lambda: set_pet_name(db, "u1", {"deviceId": "devA", "name": "モチ", "firstPerson": "おれ"}, run_tx)
               ).reason == "first_person_already_set"
    assert get_pet(db, "u1", "devA")["birthStatus"] == "born"
    assert build_ai_payload("x", a, db.docs[("pets", a)], NOW)["firstPerson"] == "ぼく"
    assert err(lambda: gen(db, lambda s, u: GOOD, pet=a)).reason == "already_born"


def test_first_person_can_be_chosen_and_must_be_valid():
    db, a, _ = setup()
    call(db)
    gen(db, lambda s, u: GOOD, pet=a)
    assert err(lambda: set_pet_name(db, "u1", {"deviceId": "devA", "name": "モチ", "firstPerson": "ぼくちゃん"}, run_tx)
               ).reason == "invalid_first_person"
    assert set_pet_name(db, "u1", {"deviceId": "devA", "name": "モチ", "firstPerson": "うち"}, run_tx)["firstPerson"] == "うち"


def test_generate_needs_personality_and_creator_and_first_generation():
    db, a, b = setup()
    assert err(lambda: gen(db, lambda s, u: GOOD, pet=a)).reason == "personality_not_set"
    call(db)
    assert err(lambda: gen(db, lambda s, u: GOOD, uid="u2", pet=a)).reason == "not_creator"
    assert err(lambda: gen(db, lambda s, u: GOOD, pet="nope")).code == "not-found"
    assert err(lambda: gen(db, lambda s, u: GOOD, pet=a, regenerate="yes")).code == "invalid-argument"
    db.docs[("pets", a)]["generation"] = 2
    assert err(lambda: gen(db, lambda s, u: GOOD, pet=a)).code == "failed-precondition"


def test_saved_profile_is_returned_without_calling_ai_unless_regenerate():
    db, a, _ = setup()
    call(db)
    gen(db, lambda s, u: GOOD, pet=a)
    r = gen(db, lambda s, u: 1 / 0, pet=a)  # AIは呼ばれない
    assert r["source"] == "ai" and r["regenerated"] is False
    other = GOOD.replace("モチ", "ココ")
    r2 = gen(db, lambda s, u: other, pet=a, regenerate=True)
    assert r2["nameCandidates"][0] == "ココ" and r2["regenerated"] is True
    assert db.docs[("pets", a)]["birthProfile"]["regenerateCount"] == 1
    assert db.docs[("pets", a)]["personalityAxes"]["activity"] == 0.2  # 性格は変えない


def test_ai_failure_or_bad_output_falls_back_to_template():
    db, a, _ = setup()
    call(db)
    r = gen(db, lambda s, u: 1 / 0, pet=a)
    assert r["source"] == "template" and len(r["nameCandidates"]) == 3 and r["firstPerson"] in ("ぼく", "わたし", "おれ", "うち")
    assert db.docs[("pets", a)]["birthProfile"]["source"] == "template" and db.docs[("pets", a)]["birthStatus"] == "profile_ready"


def test_parse_profile_rejects_bad_output():
    for bad in ('{"nameCandidates": ["a", "b"]}', "これはJSONではない", GOOD.replace('"ぼく"', '"私"'),
                GOOD.replace('"ポポ"', '"モチ"'), GOOD.replace("元気な子。", "あ" * 81), GOOD.replace('"ルル"', '""')):
        with pytest.raises((ValueError, KeyError)):
            parse_profile(bad)
    assert parse_profile(GOOD)["source"] == "ai"


def test_answers_accept_ai_vocabulary_and_base_type_is_kept():
    db, a, _ = setup()
    db.docs[("pets", a)]["baseType"] = "cat"
    r = call(db, answers={"active": 0, "affection": 1, "talkative": 2, "logic": 3, "curious": 3, "night": 0})
    assert r["personalityAxes"]["logical"] == 0.8 and r["personalityAxes"]["nightowl"] == 0.2
    assert db.docs[("pets", a)]["baseType"] == "cat" and get_pet(db, "u1", "devA")["baseType"] == "cat"


def test_birth_trait_and_primary_always_match_at_birth_even_with_ties():
    from petlogic.appearance import appearance_of
    from petlogic.birth import axes_of
    from petlogic.talk import AI_AXIS_NAMES
    import itertools
    for answers in itertools.product(range(4), repeat=6):
        axes = axes_of(list(answers))
        for pet_id in ("p1", "pet-2", "xyz"):
            a = appearance_of(pet_id, axes, "baby", fixed_order=True)
            assert AI_AXIS_NAMES[a["primary"]] == birth_trait(axes)
            assert a["secondary"] != a["primary"]


def test_secondary_uses_same_order_and_getpet_matches_birth_response():
    db, a, _ = setup()
    r = call(db, answers=(2, 2, 2, 1, 1, 0))  # activity / friendly / talkative が同点(0.6)
    ap = r["appearance"]
    assert (ap["primary"], ap["secondary"]) == ("activity", "friendly") and r["birthTrait"] == "active"
    assert get_pet(db, "u1", "devA")["appearance"]["key"] == ap["key"]
    # 誕生のながれを通っていない昔のペットは、これまでどおり(ペットごとの順)
    legacy = {n: 0.5 for n in ("activity", "friendly", "talkative", "logical", "curious", "nightowl")}
    from petlogic.appearance import appearance_of
    assert {appearance_of(f"pet{i}", legacy, "baby")["primary"] for i in range(30)} != {"activity"}


def test_unfinished_pet_received_by_exchange_counts_as_born_for_the_receiver():
    db, a, b = setup()
    call(db)  # u1 のペット a は、personality_set まで進んだところ
    assert get_pet(db, "u1", "devA")["birthStatus"] == "personality_set"
    report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a, "gotPetId": b,
                               "transactionId": "t9"}, NOW, run_tx=run_tx)
    assert get_pet(db, "u2", "devB")["birthStatus"] == "born"  # 受け取った人は、誕生のながれに入らない
    assert get_pet(db, "u1", "devA")["birthStatus"] == "born"
    assert err(lambda: gen(db, lambda s, u: GOOD, uid="u2", pet=a)).code == "permission-denied"
