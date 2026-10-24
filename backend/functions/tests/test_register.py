import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from google.api_core.exceptions import AlreadyExists

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from petlogic.register import RegisterError, register_device  # noqa: E402

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


class FakeSnap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class FakeRef:
    def __init__(self, store, name, doc_id):
        self.store, self.name, self.id = store, name, doc_id

    def get(self):
        return FakeSnap(self.store.docs.get((self.name, self.id)))


class FakeCollection:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def document(self, doc_id=None):
        if doc_id is None:
            self.store.counter += 1
            doc_id = f"auto{self.store.counter}"
        return FakeRef(self.store, self.name, doc_id)


class FakeBatch:
    def __init__(self, store):
        self.store, self.ops = store, []

    def create(self, ref, data):
        self.ops.append((ref, data))

    def commit(self):
        for ref, _ in self.ops:
            if (ref.name, ref.id) in self.store.docs:
                raise AlreadyExists("exists")
        for ref, data in self.ops:
            self.store.docs[(ref.name, ref.id)] = data


class FakeDb:
    def __init__(self):
        self.docs, self.counter = {}, 0

    def collection(self, name):
        return FakeCollection(self, name)

    def batch(self):
        return FakeBatch(self)


def test_first_call_creates_pet_and_device():
    db = FakeDb()
    r = register_device(db, "u1", "core2-01", NOW)
    assert r["isNew"] is True and r["deviceId"] == "core2-01"
    assert db.docs[("devices", "core2-01")]["currentPetId"] == r["petId"]
    pet = db.docs[("pets", r["petId"])]
    assert pet["creatorUid"] == "u1"
    assert set(pet["personalityAxes"].values()) == {0.5}
    assert pet["learnedWords"] == []


def test_second_call_returns_same_pet():
    db = FakeDb()
    first = register_device(db, "u1", "core2-01", NOW)
    second = register_device(db, "u1", "core2-01", NOW)
    assert second["petId"] == first["petId"] and second["isNew"] is False
    assert len([k for k in db.docs if k[0] == "pets"]) == 1


def test_other_user_is_denied():
    db = FakeDb()
    register_device(db, "u1", "core2-01", NOW)
    with pytest.raises(RegisterError) as e:
        register_device(db, "u2", "core2-01", NOW)
    assert e.value.code == "permission-denied"


@pytest.mark.parametrize("bad", [None, "", "a b", "x" * 65, 123, "日本語"])
def test_invalid_device_id(bad):
    with pytest.raises(RegisterError) as e:
        register_device(FakeDb(), "u1", bad, NOW)
    assert e.value.code == "invalid-argument"


def test_race_returns_existing_result():
    """確認のあとに、別の呼び出しが先に登録した場合。"""
    db = FakeDb()
    real_get = FakeRef.get
    state = {"first": True}

    def racing_get(self):
        if self.name == "devices" and state["first"]:
            state["first"] = False
            snap = real_get(self)
            db.docs[("devices", self.id)] = {"ownerUid": "u1", "currentPetId": "winner"}
            return snap
        return real_get(self)

    FakeRef.get = racing_get
    try:
        r = register_device(db, "u1", "core2-01", NOW)
    finally:
        FakeRef.get = real_get
    assert r == {"deviceId": "core2-01", "petId": "winner", "isNew": False}
