import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb  # noqa: E402
from petlogic.users import upsert_user, upsert_user_quietly, user_fields  # noqa: E402

T0 = datetime(2026, 10, 24, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 25, tzinfo=timezone.utc)
ANON = {"firebase": {"sign_in_provider": "anonymous"}}
MAIL = {"email": "a@example.com", "email_verified": False, "firebase": {"sign_in_provider": "password"}}


def test_creates_user_from_token_claims():
    db = FakeDb()
    r = upsert_user(db, "u1", ANON, T0)
    doc = db.docs[("users", "u1")]
    assert doc["uid"] == "u1" and doc["isAnonymous"] is True and doc["email"] is None
    assert doc["createdAt"] == T0 and r["isAnonymous"] is True


def test_link_to_email_updates_same_uid_and_keeps_created_at():
    db = FakeDb()
    upsert_user(db, "u1", ANON, T0)
    upsert_user(db, "u1", MAIL, T1)
    doc = db.docs[("users", "u1")]
    assert doc["email"] == "a@example.com" and doc["isAnonymous"] is False
    assert doc["signInProvider"] == "password" and doc["createdAt"] == T0 and doc["lastSeenAt"] == T1


def test_missing_token_is_safe():
    assert user_fields(None) == {"email": None, "signInProvider": None, "isAnonymous": False, "emailVerified": False}


def test_quiet_version_swallows_errors():
    class Bad:
        def collection(self, name):
            raise RuntimeError("down")
    upsert_user_quietly(Bad(), "u1", ANON, T0)


# ---- users/{uid}.firstPetId ----
from petlogic.register import register_device  # noqa: E402
from petlogic.users import ensure_first_pet, oldest_created_pet  # noqa: E402


def test_first_pet_is_recorded_on_first_device_only():
    db = FakeDb()
    a = register_device(db, "u1", "devA", T0)["petId"]
    assert db.docs[("users", "u1")]["firstPetId"] == a
    register_device(db, "u1", "devB", T1)  # 2体目を作っても、変わらない
    assert db.docs[("users", "u1")]["firstPetId"] == a


def test_first_pet_keeps_existing_user_fields():
    db = FakeDb()
    upsert_user(db, "u1", MAIL, T0)
    a = register_device(db, "u1", "devA", T1)["petId"]
    doc = db.docs[("users", "u1")]
    assert doc["firstPetId"] == a and doc["email"] == "a@example.com" and doc["createdAt"] == T0
    upsert_user(db, "u1", MAIL, T1)  # あとから記録を更新しても、消えない
    assert db.docs[("users", "u1")]["firstPetId"] == a


def test_user_doc_created_by_register_gets_filled_by_upsert():
    db = FakeDb()
    a = register_device(db, "u1", "devA", T0)["petId"]
    upsert_user(db, "u1", ANON, T1)
    doc = db.docs[("users", "u1")]
    assert doc["firstPetId"] == a and doc["isAnonymous"] is True and doc["uid"] == "u1"


def test_ensure_backfills_old_users_and_handles_no_pet():
    db = FakeDb()
    assert ensure_first_pet(db, "nobody", T0) is None and ("users", "nobody") not in db.docs
    db.docs[("users/u9/createdPets", "old")] = {"createdAt": T0}
    db.docs[("users/u9/createdPets", "new")] = {"createdAt": T1}
    db.docs[("users", "u9")] = {"uid": "u9", "email": "x@example.com"}  # 昔のユーザー(firstPetId なし)
    assert oldest_created_pet(db, "u9") == "old"
    assert ensure_first_pet(db, "u9", T1) == "old"
    assert db.docs[("users", "u9")]["firstPetId"] == "old" and db.docs[("users", "u9")]["email"] == "x@example.com"
    db.docs[("users/u9/createdPets", "older")] = {"createdAt": T0 - (T1 - T0)}
    assert ensure_first_pet(db, "u9", T1) == "old"  # 一度決まったら、変わらない
