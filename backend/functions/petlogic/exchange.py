"""すれ違い交換。2台の端末が、持っているペットを入れ替える。

記録の置き場所:
  exchanges/{transactionId}  交換1回の記録(confirmed か cancelled)
  handoffs/{handoffId}       手渡しの履歴
  devices/{deviceId}         currentPetId(その端末が持つべきペット)を書き換える
  pets/{petId}               generation(世代)を1増やす
"""
import re

from .errors import ApiError
from .growth import require_full_gauge
from .register import validate_device_id
from .store import run_in_transaction

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _id(value, name):
    if not isinstance(value, str) or not _ID.match(value):
        raise ApiError("invalid-argument", f"{name} は、英数字と _ - だけの、1〜64文字にしてください")
    return value


def _mismatch():
    return ApiError(
        "failed-precondition",
        "同じ transactionId が、別の内容の交換に使われています",
        "transaction_mismatch",
    )


def _own_device(db, tx, uid, device_id):
    ref = db.collection("devices").document(device_id)
    snap = ref.get(transaction=tx)
    if not snap.exists:
        raise ApiError("not-found", f"端末 {device_id} が登録されていません")
    data = snap.to_dict()
    if data.get("ownerUid") != uid:
        raise ApiError("permission-denied", "自分の端末ではありません")
    return ref, data


def _perspective(ex, device_id):
    """その端末から見た、(手放したペット, 受け取ったペット)。"""
    if device_id == ex["reporterDeviceId"]:
        return ex["givenPetId"], ex["gotPetId"]
    return ex["gotPetId"], ex["givenPetId"]


def _confirmed_fields(ex, device_id, transaction_id):
    if device_id not in (ex["reporterDeviceId"], ex["peerDeviceId"]):
        raise _mismatch()
    given, received = _perspective(ex, device_id)
    return {
        "transactionId": transaction_id,
        "handoffId": ex["handoffId"],
        "givenPetId": given,
        "receivedPetId": received,
        "receivedPetGeneration": ex["generations"][received],
    }


def report_exchange(db, uid, data, now, run_tx=run_in_transaction):
    data = data or {}
    my_id = validate_device_id(data.get("myDeviceId"))
    peer_id = validate_device_id(data.get("peerDeviceId"))
    given = _id(data.get("givenPetId"), "givenPetId")
    got = _id(data.get("gotPetId"), "gotPetId")
    tid = _id(data.get("transactionId"), "transactionId")
    if my_id == peer_id:
        raise ApiError("invalid-argument", "自分自身とは、交換できません")
    if given == got:
        raise ApiError("invalid-argument", "同じペット同士は、交換できません")
    location = data.get("location")
    location = location[:100] if isinstance(location, str) else None
    rssi = data.get("rssi")
    rssi = rssi if isinstance(rssi, int) and not isinstance(rssi, bool) else None

    def work(tx):
        ex_ref = db.collection("exchanges").document(tid)
        my_ref, my = _own_device(db, tx, uid, my_id)
        ex_snap = ex_ref.get(transaction=tx)

        if ex_snap.exists:
            ex = ex_snap.to_dict()
            if ex["status"] == "cancelled":
                raise ApiError(
                    "failed-precondition", "この交換は、取り消されています", "exchange_cancelled"
                )
            fields = _confirmed_fields(ex, my_id, tid)
            other = ex["peerDeviceId"] if my_id == ex["reporterDeviceId"] else ex["reporterDeviceId"]
            if peer_id != other or (given, got) != (fields["givenPetId"], fields["receivedPetId"]):
                raise _mismatch()
            replayed = my_id == ex["reporterDeviceId"]
            return {
                "status": "done" if replayed else "already_done",
                "replayed": replayed,
                **fields,
            }

        peer_ref = db.collection("devices").document(peer_id)
        peer_snap = peer_ref.get(transaction=tx)
        if not peer_snap.exists:
            raise ApiError("not-found", f"端末 {peer_id} が登録されていません")
        peer = peer_snap.to_dict()
        given_ref = db.collection("pets").document(given)
        got_ref = db.collection("pets").document(got)
        given_snap = given_ref.get(transaction=tx)
        got_snap = got_ref.get(transaction=tx)
        if not given_snap.exists or not got_snap.exists:
            raise ApiError("not-found", "ペットが登録されていません")

        if my.get("currentPetId") != given or peer.get("currentPetId") != got:
            raise ApiError("failed-precondition", "報告が、サーバーの状態と合いません")

        if require_full_gauge(db):
            not_ready = [pid for pid, snap in ((given, given_snap), (got, got_snap))
                         if snap.to_dict().get("gauge", 0.0) < 1.0]
            if not_ready:
                raise ApiError(
                    "failed-precondition", "ゲージが満タンではありません", "pet_not_ready",
                    {"petIds": not_ready},
                )

        gen_given = given_snap.to_dict().get("generation", 1) + 1
        gen_got = got_snap.to_dict().get("generation", 1) + 1
        handoff_ref = db.collection("handoffs").document()
        tx.update(given_ref, {"generation": gen_given, "points": 0.0, "gauge": 0.0,
                              "ownerUid": peer.get("ownerUid"), "generationStartedAt": now})
        tx.update(got_ref, {"generation": gen_got, "points": 0.0, "gauge": 0.0,
                            "ownerUid": uid, "generationStartedAt": now})
        tx.update(my_ref, {"currentPetId": got, "lastHandoffId": handoff_ref.id})
        tx.update(peer_ref, {"currentPetId": given, "lastHandoffId": handoff_ref.id})
        record = {
            "transactionId": tid,
            "reporterDeviceId": my_id,
            "peerDeviceId": peer_id,
            "givenPetId": given,
            "gotPetId": got,
            "location": location,
            "rssi": rssi,
            "createdAt": now,
        }
        tx.create(
            handoff_ref,
            {
                **record,
                # 手放した時点で終わった代(要約の対象)
                "endedGenerations": {given: gen_given - 1, got: gen_got - 1},
                "summaryStatus": "pending",
                "journeyStatus": "pending",
                # 終わった代で話した回数(ポイントは、この交換で0に戻るので、ここで控える)
                "endedTalkCounts": {given: int(given_snap.to_dict().get("points", 0)),
                                    got: int(got_snap.to_dict().get("points", 0))},
            },
        )
        tx.create(
            ex_ref,
            {
                **record,
                "status": "confirmed",
                "handoffId": handoff_ref.id,
                "generations": {given: gen_given, got: gen_got},
            },
        )
        return {
            "status": "done",
            "replayed": False,
            "transactionId": tid,
            "handoffId": handoff_ref.id,
            "givenPetId": given,
            "receivedPetId": got,
            "receivedPetGeneration": gen_got,
        }

    return run_tx(db, work)


def get_exchange_result(db, uid, data):
    """読むだけ。交換の結果を答える。"""
    data = data or {}
    tid = _id(data.get("transactionId"), "transactionId")
    my_id = validate_device_id(data.get("myDeviceId"))
    _, my = _own_device(db, None, uid, my_id)
    snap = db.collection("exchanges").document(tid).get()
    if not snap.exists:
        return {"status": "unknown", "transactionId": tid}
    ex = snap.to_dict()
    if ex["status"] == "cancelled":
        return {"status": "cancelled", "transactionId": tid}
    return {
        "status": "confirmed",
        **_confirmed_fields(ex, my_id, tid),
        "currentPetId": my.get("currentPetId"),
    }


def cancel_exchange(db, uid, data, now, run_tx=run_in_transaction):
    """まだ確定していない交換を、取り消す。確定済みなら、取り消さずに、その結果を返す。"""
    data = data or {}
    tid = _id(data.get("transactionId"), "transactionId")
    my_id = validate_device_id(data.get("myDeviceId"))
    peer_id = validate_device_id(data.get("peerDeviceId"))

    def work(tx):
        my_ref, my = _own_device(db, tx, uid, my_id)
        ex_ref = db.collection("exchanges").document(tid)
        snap = ex_ref.get(transaction=tx)
        if snap.exists:
            ex = snap.to_dict()
            if ex["status"] == "cancelled":
                return {"status": "cancelled", "transactionId": tid}
            return {
                "status": "confirmed",
                **_confirmed_fields(ex, my_id, tid),
                "currentPetId": my.get("currentPetId"),
            }
        tx.create(
            ex_ref,
            {
                "status": "cancelled",
                "transactionId": tid,
                "myDeviceId": my_id,
                "peerDeviceId": peer_id,
                "createdAt": now,
            },
        )
        return {"status": "cancelled", "transactionId": tid}

    return run_tx(db, work)
