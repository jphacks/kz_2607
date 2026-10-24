import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb  # noqa: E402
from petlogic.errors import ApiError  # noqa: E402
from petlogic.pet import get_pet  # noqa: E402
from petlogic.register import register_device  # noqa: E402

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def test_returns_display_fields_without_owner_info():
    db = FakeDb()
    reg = register_device(db, "u1", "core2-01", NOW)
    r = get_pet(db, "u1", "core2-01")
    assert r["petId"] == reg["petId"] and r["deviceId"] == "core2-01"
    assert r["name"] is None and r["generation"] == 1
    assert set(r["personalityAxes"].values()) == {0.5}
    assert r["learnedWords"] == [] and r["createdAt"].startswith("2026-10-24")
    assert "creatorUid" not in r and "ownerUid" not in r


def test_follows_current_pet_after_change():
    db = FakeDb()
    register_device(db, "u1", "core2-01", NOW)
    db.docs[("pets", "other")] = {"generation": 3, "learnedWords": ["こんにちは"]}
    db.docs[("devices", "core2-01")]["currentPetId"] = "other"
    r = get_pet(db, "u1", "core2-01")
    assert r["petId"] == "other" and r["generation"] == 3
    assert r["learnedWords"] == ["こんにちは"]


@pytest.mark.parametrize("uid,dev,code", [
    ("u2", "core2-01", "permission-denied"),
    ("u1", "nothing", "not-found"),
    ("u1", "", "invalid-argument"),
])
def test_errors(uid, dev, code):
    db = FakeDb()
    register_device(db, "u1", "core2-01", NOW)
    with pytest.raises(ApiError) as e:
        get_pet(db, uid, dev)
    assert e.value.code == code
