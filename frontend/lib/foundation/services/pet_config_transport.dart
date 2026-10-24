import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

/// The 20-byte pet configuration frames used by the Core2 demo firmware.
/// Each frame carries up to five UTF-8 bytes and is acknowledged separately.
class PetConfigTransport {
  PetConfigTransport(this.write);

  final Future<void> Function(List<int>) write;
  bool _closed = false;
  bool _sending = false;
  String? _transactionId;
  int _waitingSequence = -1;
  Completer<void>? _frameAck;
  Completer<Map<String, dynamic>>? _configAck;
  final Map<int, List<int>> _incoming = {};
  int? _incomingCount;

  static List<int> _frame(
    String transactionId,
    int type,
    int sequence,
    int count,
    List<int> payload,
  ) {
    final frame = Uint8List(20);
    frame[0] = 70; // F
    frame[1] = 1;
    frame[2] = type;
    for (var i = 0; i < 8; i++) {
      frame[4 + i] = int.parse(
        transactionId.substring(14 - i * 2, 16 - i * 2),
        radix: 16,
      );
    }
    frame[12] = sequence;
    frame[13] = count;
    frame[14] = payload.length;
    frame.setRange(15, 15 + payload.length, payload);
    return frame;
  }

  /// Returns true when [bytes] are protocol frames rather than status JSON.
  bool receive(List<int> bytes) {
    if (bytes.isEmpty || bytes[0] != 70) return false;
    if (_closed || bytes.length != 20 || bytes[1] != 1 || bytes[3] != 0) {
      return true;
    }
    final transactionId = bytes
        .sublist(4, 12)
        .reversed
        .map((b) => b.toRadixString(16).padLeft(2, '0'))
        .join()
        .toUpperCase();
    if (transactionId != _transactionId) return true;

    final sequence = bytes[12];
    if (bytes[2] == 2) {
      if (sequence == _waitingSequence &&
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
    if (_incomingCount != count) {
      _incoming.clear();
      _incomingCount = count;
    }
    final part = bytes.sublist(15, 15 + length);
    final previous = _incoming[sequence];
    if (previous != null && !_sameBytes(previous, part)) return true;
    _incoming[sequence] = part;
    unawaited(write(_frame(transactionId, 2, sequence, 0, const []))
        .catchError((Object _) {}));

    if (_incoming.length == count) {
      try {
        final message = jsonDecode(utf8.decode([
          for (var i = 0; i < count; i++) ..._incoming[i]!,
        ]));
        if (message is Map<String, dynamic> &&
            message['type'] == 'pet_config_ack' &&
            message['transactionId'] == transactionId &&
            message['status'] == 'received' &&
            _configAck != null &&
            !_configAck!.isCompleted) {
          _configAck!.complete(message);
        }
      } on FormatException {
        // Ignore malformed application acknowledgements.
      }
      _incoming.clear();
      _incomingCount = null;
    }
    return true;
  }

  Future<void> sendConfig({required String deviceId, required String petId}) async {
    if (_closed || _sending) throw StateError('BLE設定を送信できません');
    if (petId.isEmpty) throw const FormatException('petIdが空です');
    final random = Random.secure();
    final transactionId = List.generate(8, (_) => random.nextInt(256))
        .map((b) => b.toRadixString(16).padLeft(2, '0'))
        .join()
        .toUpperCase();
    final payload = utf8.encode(jsonEncode({
      'type': 'pet_config',
      'transactionId': transactionId,
      'deviceId': deviceId,
      'petId': petId,
    }));
    final count = (payload.length + 4) ~/ 5;
    if (count > 255) throw StateError('petId設定データが長すぎます');

    _sending = true;
    _transactionId = transactionId;
    _configAck = Completer<Map<String, dynamic>>();
    try {
      for (var sequence = 0; sequence < count; sequence++) {
        _waitingSequence = sequence;
        _frameAck = Completer<void>();
        final packet = _frame(transactionId, 1, sequence, count,
            payload.sublist(sequence * 5, min(sequence * 5 + 5, payload.length)));
        var acknowledged = false;
        for (var attempt = 0; attempt < 4; attempt++) {
          if (_closed) throw StateError('BLE接続が終了しました');
          await write(packet);
          try {
            await _frameAck!.future.timeout(const Duration(milliseconds: 500));
            acknowledged = true;
            break;
          } on TimeoutException {
            // A duplicate frame is safe; Core2 ACKs the same sequence again.
          }
        }
        if (!acknowledged) throw TimeoutException('Core2からフレームACKが届きません');
      }
      final ack = await _configAck!.future.timeout(const Duration(seconds: 8));
      if (_closed) throw StateError('BLE接続が終了しました');
      if (ack['deviceId'] != deviceId) {
        throw StateError('Core2の設定完了ACKの端末IDが一致しません');
      }
    } finally {
      _sending = false;
      _transactionId = null;
      _waitingSequence = -1;
      _frameAck = null;
      _configAck = null;
      _incoming.clear();
      _incomingCount = null;
    }
  }

  void close() {
    _closed = true;
    _incoming.clear();
  }

  static bool _sameBytes(List<int> a, List<int> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}
