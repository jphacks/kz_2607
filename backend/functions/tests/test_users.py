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
