import 'dart:async';
import 'dart:math';
import 'dart:typed_data';

/// Reference Core2 protocol: START / four-frame DATA windows / END, cumulative ACK.
/// Transport is injected so loss, retries and disconnects can be tested without BLE.
class ReplyVoiceSender {
  ReplyVoiceSender({
    required this.write,
    required Stream<List<int>> acknowledgements,
    this.ackTimeout = const Duration(milliseconds: 700),
    this.attempts = 7,
    this.onMetrics,
  }) {
    _subscription = acknowledgements.listen(
      _receive,
      onError: (Object e) {
        _error = '音声ACK受信失敗: $e';
        _wake();
      },
    );
  }
  final Future<void> Function(List<int>, bool withoutResponse) write;
  final Duration ackTimeout;
  final int attempts;
  final void Function(Map<String, Object?>)? onMetrics;
  final Stopwatch _ackWait = Stopwatch();
  int _timeouts = 0, _writes = 0, _resent = 0;
  final Set<int> _sequences = {};
  StreamSubscription<List<int>>? _subscription;
  Completer<void>? _pending;
  bool _closed = false, _sending = false;
  int _session = 0, _ack = -1, _maxSent = 0, _target = -1;
  String? _error;
  int retryCount = 0;

  void _wake() {
    final p = _pending;
    if (p != null && !p.isCompleted) p.complete();
  }

  void _receive(List<int> packet) {
    if (_closed || !_sending || packet.length != 4 || packet[1] != _session) {
      return;
    }
    if (packet[0] == 4) {
      _error = switch (packet[2]) {
        1 => 'Core2が音声形式を拒否しました',
        2 => 'Core2が録音・再生中です',
        3 => 'Core2の音声メモリが不足しています',
        _ => 'Core2が音声を拒否しました',
      };
      _wake();
    } else if (packet[0] == 2) {
      final sequence = packet[2] | packet[3] << 8;
      if (sequence > _maxSent) return;
      _ack = max(_ack, sequence);
      if (_ack >= _target) _wake();
    }
  }

  void _check() {
    if (_closed) throw StateError('Core2との接続が切れました');
    if (_error != null) throw StateError(_error!);
  }

  Future<void> _untilAck(int target, Future<void> Function() send) async {
    _target = target;
    for (var attempt = 0; attempt < attempts; attempt++) {
      _check();
      if (attempt > 0) retryCount++;
      final pending = Completer<void>();
      _pending = pending;
      try {
        await send();
        _check();
        if (_ack >= target) return;
        _ackWait.start();
        try {
          await pending.future.timeout(ackTimeout);
        } finally {
          _ackWait.stop();
        }
        _check();
        if (_ack >= target) return;
      } on TimeoutException {
        _timeouts++;
        if (attempt == attempts - 1) {
          throw StateError('Core2から音声の受信確認が届きませんでした');
        }
      } finally {
        if (identical(_pending, pending)) _pending = null;
      }
    }
    throw StateError('Core2への音声転送に失敗しました');
  }

  Future<void> send({
    required Uint8List bytes,
    required int sampleCount,
    required int chunkSize,
    int cloudToSendUs = 0,
    void Function(int sent, int total)? onProgress,
  }) async {
    if (_closed || _sending) throw StateError('返答音声を転送できません');
    if (sampleCount < 1 ||
        sampleCount > 480000 ||
        bytes.length != (sampleCount + 1) ~/ 2 ||
        chunkSize < 1 ||
        chunkSize > 240) {
      throw const FormatException('Core2向け音声サイズが不正です');
    }
    final packets = (bytes.length + chunkSize - 1) ~/ chunkSize;
    if (packets >= 65535) throw const FormatException('返答音声が長すぎます');
    _sending = true;
    _session = (_session + 1) & 255;
    _ack = -1;
    _maxSent = 0;
    _error = null;
    retryCount = 0;
    _timeouts = _writes = _resent = 0;
    _sequences.clear();
    _ackWait.reset();
    final clock = Stopwatch()..start();
    int? startAckUs, dataUs, endAckUs;
    var success = false;
    try {
      onProgress?.call(0, bytes.length);
      await _untilAck(
        0,
        () => write([
          1,
          _session,
          sampleCount & 255,
          sampleCount >> 8 & 255,
          sampleCount >> 16 & 255,
          sampleCount >> 24 & 255,
          1,
          chunkSize,
        ], false),
      );
      startAckUs = clock.elapsedMicroseconds;
      for (var first = 1; first <= packets; first += 4) {
        final last = min(first + 3, packets);
        await _untilAck(last, () async {
          for (var sequence = first; sequence <= last; sequence++) {
            _check();
            final offset = (sequence - 1) * chunkSize;
            _maxSent = max(_maxSent, sequence);
            _writes++;
            if (!_sequences.add(sequence)) _resent++;
            await write([
              2,
              _session,
              sequence & 255,
              sequence >> 8,
              ...bytes.sublist(offset, min(offset + chunkSize, bytes.length)),
            ], true);
          }
        });
        onProgress?.call(min(last * chunkSize, bytes.length), bytes.length);
      }
      dataUs = clock.elapsedMicroseconds - startAckUs;
      final endStartUs = clock.elapsedMicroseconds;
      _maxSent = packets + 1;
      await _untilAck(
        packets + 1,
        () => write([
          3,
          _session,
          (packets + 1) & 255,
          (packets + 1) >> 8,
        ], false),
      );
      endAckUs = clock.elapsedMicroseconds - endStartUs;
      success = true;
    } finally {
      _pending = null;
      _sending = false;
      clock.stop();
      onMetrics?.call({
        'direction': 'down',
        'success': success,
        'session': _session,
        'audioBytes': bytes.length,
        'sampleCount': sampleCount,
        'chunkSize': chunkSize,
        'packets': packets,
        'dataWrites': _writes,
        'resentPackets': _resent,
        'retransmitRate': _writes == 0 ? 0.0 : _resent / _writes,
        'retries': retryCount,
        'ackTimeouts': _timeouts,
        'ackWindow': 4,
        'cloudToStartAckUs': startAckUs == null
            ? null
            : cloudToSendUs + startAckUs,
        'dataUs': dataUs,
        'endAckUs': endAckUs,
        'ackWaitUs': _ackWait.elapsedMicroseconds,
        'transferUs': clock.elapsedMicroseconds,
        'totalUs': cloudToSendUs + clock.elapsedMicroseconds,
      });
    }
  }

  Future<void> close() async {
    _closed = true;
    _wake();
    await _subscription?.cancel();
  }
}
