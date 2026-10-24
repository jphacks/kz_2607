"""Firestoreのトランザクション実行。テストでは、差し替える。"""
from firebase_admin import firestore


def run_in_transaction(db, fn):
    """fn(tx) を、1回のトランザクションとして実行する。競合したら、自動で再試行される。"""

    @firestore.transactional
    def _run(tx):
        return fn(tx)

    return _run(db.transaction())
