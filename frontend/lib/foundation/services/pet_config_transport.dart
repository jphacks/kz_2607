import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

/// Fixed 20-byte frames: F, version 1, DATA=1, ACK=2; little-endian 64-bit ID.
class PetConfigTransport {
  PetConfigTransport(this.write);
  final Future<void> Function(List<int>) write;
  void Function(Map<String, dynamic>)? onMessage;
  final Map<String, _IncomingMessage> _incoming = {};
  String _expectedAckType = 'pet_config_ack';
  bool _closed = false;
  bool _sending = false;
  String? _tx;
  Completer<void>? _frameAck;
  Completer<Map<String, dynamic>>? _messageAck;
  int _waitingSequence = -1;

  static List<int> frame(
    String tx,
    int type,
    int sequence,
    int count,
    List<int> payload,
  ) {
    final bytes = Uint8List(20);
    bytes[0] = 70;
    bytes[1] = 1;
    bytes[2] = type;
    for (var i = 0; i < 8; i++) {
      bytes[4 + i] = int.parse(tx.substring(14 - 2 * i, 16 - 2 * i), radix: 16);
    }
    bytes[12] = sequence;
    bytes[13] = count;
    bytes[14] = payload.length;
    bytes.setRange(15, 15 + payload.length, payload);
    return bytes;
  }

  /// Returns true for binary transport packets, keeping them out of JSON status parsing.
  bool receive(List<int> bytes) {
    if (bytes.isEmpty || bytes[0] != 70) return false;
    if (_closed || bytes.length != 20 || bytes[1] != 1 || bytes[3] != 0) {
      return true;
    }
    final tx = bytes
        .sublist(4, 12)
        .reversed
        .map((x) => x.toRadixString(16).padLeft(2, '0'))
        .join()
        .toUpperCase();

    final sequence = bytes[12];
    if (bytes[2] == 2) {
      if (tx == _tx &&
          sequence == _waitingSequence &&
          bytes[13] == 0 &&
          bytes[14] == 0 &&
          _frameAck != null &&
          !_frameAck!.isCompleted) {
        _frameAck!.complete();
      }
      return true;
    }
    final count = bytes[13];
    final length = bytes[14];
    if (bytes[2] != 1 ||
        count == 0 ||
        sequence >= count ||
        length == 0 ||
        length > 5) {
      return true;
    }
    // exchange_pending and exchange_result_ack use the same transaction ID.
    // Keep their fragments separate when the two messages overlap.
    final incomingKey = '$tx:$count';
    if (!_incoming.containsKey(incomingKey)) {
      if (_incoming.length >= 8) return true;
      _incoming[incomingKey] = _IncomingMessage(
        count,
        () => _incoming.remove(incomingKey),
      );
    }
    final incoming = _incoming[incomingKey]!;
    final part = bytes.sublist(15, 15 + length);
    final previous = incoming.parts[sequence];
    if (previous != null && !const ListEqualityHelper().same(previous, part)) {
      return true;
    }
    incoming.parts[sequence] = part;
    unawaited(
      write(frame(tx, 2, sequence, 0, const [])).catchError((Object _) {}),
    );
    if (incoming.parts.length == count) {
      incoming.timer.cancel();
      _incoming.remove(incomingKey);
      try {
        final data = jsonDecode(
          utf8.decode([for (var i = 0; i < count; i++) ...incoming.parts[i]!]),
        );
        if (data is Map<String, dynamic> && data['transactionId'] == tx) {
          if (tx == _tx &&
              data['type'] == _expectedAckType &&
              data['status'] == 'received' &&
              _messageAck != null &&
              !_messageAck!.isCompleted) {
            _messageAck!.complete(data);
          }
          onMessage?.call(data);
        }
      } catch (_) {
        /* Ignore malformed messages; no application acknowledgement. */
      }
    }
    return true;
  }

  Future<void> sendConfig({
    required String deviceId,
    required String petId,
  }) async {
    final random = Random.secure();
    final tx = List.generate(
      8,
      (_) => random.nextInt(256),
    ).map((x) => x.toRadixString(16).padLeft(2, '0')).join().toUpperCase();
    final ack = await sendMessage({
      'type': 'pet_config',
      'transactionId': tx,
      'deviceId': deviceId,
      'petId': petId,
    }, ackType: 'pet_config_ack');
    if (ack['deviceId'] != deviceId) throw StateError('設定完了ACKの端末が一致しません。');
  }

  Future<Map<String, dynamic>> sendMessage(
    Map<String, dynamic> message, {
    required String ackType,
  }) async {
    if (_closed || _sending) throw StateError('BLE送信は実行できません。');
    final tx = message['transactionId'];
    if (tx is! String || !RegExp(r'^[0-9A-F]{16}$').hasMatch(tx)) {
      throw const FormatException('transactionIdが不正です');
    }
    _sending = true;
    _tx = tx;
    _expectedAckType = ackType;
    for (final key in _incoming.keys.where((key) => key.startsWith('$tx:')).toList()) {
      _incoming.remove(key)?.timer.cancel();
    }
    _messageAck = Completer<Map<String, dynamic>>();
    final payload = utf8.encode(jsonEncode(message));
    final count = (payload.length + 4) ~/ 5;
    try {
      if (count > 255) throw StateError('設定データが大きすぎます。');
      for (var sequence = 0; sequence < count; sequence++) {
        final packet = frame(
          tx,
          1,
          sequence,
          count,
          payload.sublist(sequence * 5, min(sequence * 5 + 5, payload.length)),
        );
        _waitingSequence = sequence;
        _frameAck = Completer<void>();
        var acknowledged = false;
        for (var attempt = 0; attempt < 4; attempt++) {
          if (_closed) throw StateError('BLE接続が終了しました。');
          await write(packet);
          try {
            await _frameAck!.future.timeout(const Duration(milliseconds: 500));
            acknowledged = true;
            break;
          } on TimeoutException {
            /* Initial send plus at most three retries. */
          }
        }
        if (!acknowledged) {
          throw TimeoutException('Core2のフレームACKが届きません。再送信してください。');
        }
      }
      final ack = await _messageAck!.future.timeout(const Duration(seconds: 8));
      if (_closed) throw StateError('BLE接続が終了しました。');
      return ack;
    } finally {
      _sending = false;
      _waitingSequence = -1;
      _frameAck = null;
      _messageAck = null;
      _tx = null;
    }
  }

  void close() {
    _closed = true;
    for (final incoming in _incoming.values) {
      incoming.timer.cancel();
    }
    _incoming.clear();
    onMessage = null;
  }
}

class ListEqualityHelper {
  const ListEqualityHelper();
  bool same(List<int> a, List<int> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}

class _IncomingMessage {
  _IncomingMessage(this.count, void Function() expire) {
    timer = Timer(const Duration(seconds: 15), expire);
  }
  final int count;
  final parts = <int, List<int>>{};
  late final Timer timer;
}
