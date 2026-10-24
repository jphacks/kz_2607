"""テスト用の、Firestoreの模擬。"""
from google.api_core.exceptions import AlreadyExists


class FakeSnap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class FakeRef:
    def __init__(self, store, name, doc_id):
        self.store, self.name, self.id = store, name, doc_id

    def collection(self, sub):
        return FakeCollection(self.store, f"{self.name}/{self.id}/{sub}")

    def get(self, transaction=None):
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


class FakeTx:
    """書き込みは、関数が最後まで成功したときだけ、まとめて反映する。"""

    def __init__(self, store):
        self.store, self.ops = store, []

    def create(self, ref, data):
        self.ops.append(("create", ref, data))

    def update(self, ref, data):
        self.ops.append(("update", ref, data))

    def set(self, ref, data):
        self.ops.append(("set", ref, data))

    def commit(self):
        for kind, ref, data in self.ops:
            key = (ref.name, ref.id)
            if kind == "set":
                self.store.docs[key] = dict(data)
            elif kind == "create":
                assert key not in self.store.docs, f"already exists: {key}"
                self.store.docs[key] = dict(data)
            else:
                assert key in self.store.docs, f"missing: {key}"
                self.store.docs[key].update(data)


class FakeDb:
    def __init__(self):
        self.docs, self.counter = {}, 0

    def collection(self, name):
        return FakeCollection(self, name)

    def batch(self):
        return FakeBatch(self)


def run_tx(db, fn):
    tx = FakeTx(db)
    result = fn(tx)
    tx.commit()
    return result
