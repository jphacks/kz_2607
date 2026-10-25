import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

/// Android -> Core2 PNG transfer. The Core2 firmware must expose the image
/// DATA (write) and ACK (notify) characteristics before this can run.
class PetImageSender {
  PetImageSender({
    required this.write,
    required Stream<List<int>> acknowledgements,
    this.ackTimeout = const Duration(milliseconds: 700),
    this.attempts = 7,
    this.onMetrics,
  }) {
    _subscription = acknowledgements.listen(_receive, onError: (Object error) {
      _error = '画像ACK受信失敗: $error';
      _wake();
    });
  }

  static const int maxImageBytes = 128 * 1024;
  static const int _window = 8;
  static const List<int> _pngSignature = [137, 80, 78, 71, 13, 10, 26, 10];
  final Future<void> Function(List<int>, bool withoutResponse) write;
  final Duration ackTimeout;
  final int attempts;
  final void Function(Map<String, Object?>)? onMetrics;
  StreamSubscription<List<int>>? _subscription;
  Completer<void>? _pending;
  bool _closed = false, _sending = false;
  int _session = 0, _ack = -1, _target = -1, _maxSent = -1;
  String? _error;

  static int crc32(Uint8List bytes) {
    var crc = 0xffffffff;
    for (final byte in bytes) {
      crc ^= byte;
      for (var bit = 0; bit < 8; bit++) {
        crc = (crc >>> 1) ^ ((crc & 1) == 0 ? 0 : 0xedb88320);
      }
    }
    return (crc ^ 0xffffffff) & 0xffffffff;
  }

  static bool _isPng(Uint8List bytes) {
    if (bytes.length < _pngSignature.length) return false;
    for (var i = 0; i < _pngSignature.length; i++) {
      if (bytes[i] != _pngSignature[i]) return false;
    }
    return true;
  }

  void _wake() {
    final pending = _pending;
    if (pending != null && !pending.isCompleted) pending.complete();
  }

  void _receive(List<int> packet) {
    if (_closed || !_sending || packet.length != 4 || packet[1] != _session) {
      return;
    }
    if (packet[0] == 4) {
      _error = switch (packet[2]) {
        1 => 'Core2が画像形式を拒否しました',
        2 => 'Core2が音声・画像処理中です',
        3 => 'Core2の画像メモリが不足しています',
        4 => 'Core2で画像の検査に失敗しました',
        _ => 'Core2が画像を拒否しました',
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
      final pending = Completer<void>();
      _pending = pending;
      try {
        await send();
        _check();
        if (_ack >= target) return;
        await pending.future.timeout(ackTimeout);
        _check();
        if (_ack >= target) return;
      } on TimeoutException {
        if (attempt == attempts - 1) {
          throw StateError('Core2から画像の受信確認が届きませんでした');
        }
      } finally {
        if (identical(_pending, pending)) _pending = null;
      }
    }
    throw StateError('Core2への画像転送に失敗しました');
  }

  Future<void> send({
    required Uint8List png,
    required String petId,
    required int width,
    required int height,
    required int chunkSize,
    void Function(int sent, int total, Duration elapsed)? onProgress,
  }) async {
    if (_closed || _sending) throw StateError('画像を転送できません');
    if (petId.isEmpty || width < 1 || width > 320 || height < 1 || height > 240 ||
        png.length > maxImageBytes ||
        chunkSize < 1 || chunkSize > 240 ||
        !_isPng(png)) {
      throw const FormatException('Core2向けPNGのサイズ・形式が不正です');
    }
    final packets = (png.length + chunkSize - 1) ~/ chunkSize;
    if (packets >= 65535) throw const FormatException('画像のパケット数が多すぎます');
    _sending = true;
    _session = (_session + 1) & 255;
    _ack = -1;
    _maxSent = 0;
    _error = null;
    final clock = Stopwatch()..start();
    var writes = 0, retries = 0;
    var success = false;
    try {
      onProgress?.call(0, png.length, clock.elapsed);
      final checksum = crc32(png);
      final petChecksum = crc32(Uint8List.fromList(utf8.encode(petId)));
      await _untilAck(0, () => write([
        1, _session, width & 255, width >> 8, height & 255, height >> 8,
        1, // PNG
        chunkSize,
        png.length & 255, png.length >> 8 & 255,
        png.length >> 16 & 255, png.length >> 24 & 255,
        checksum & 255, checksum >> 8 & 255,
        checksum >> 16 & 255, checksum >> 24 & 255,
        petChecksum & 255, petChecksum >> 8 & 255,
        petChecksum >> 16 & 255, petChecksum >> 24 & 255,
      ], false));
      for (var first = 1; first <= packets; first += _window) {
        final last = min(first + _window - 1, packets);
        var attempt = 0;
        await _untilAck(last, () async {
          if (attempt++ > 0) retries++;
          for (var sequence = first; sequence <= last; sequence++) {
            _check();
            final offset = (sequence - 1) * chunkSize;
            _maxSent = max(_maxSent, sequence);
            writes++;
            await write([
              2, _session, sequence & 255, sequence >> 8,
              ...png.sublist(offset, min(offset + chunkSize, png.length)),
            ], true);
          }
        });
        onProgress?.call(min(last * chunkSize, png.length), png.length, clock.elapsed);
      }
      _maxSent = packets + 1;
      await _untilAck(packets + 1, () => write([
        3, _session, (packets + 1) & 255, (packets + 1) >> 8,
      ], false));
      success = true;
    } finally {
      _pending = null;
      _sending = false;
      clock.stop();
      onMetrics?.call({
        'direction': 'image_down',
        'success': success,
        'imageBytes': png.length,
        'width': width,
        'height': height,
        'packets': packets,
        'dataWrites': writes,
        'retries': retries,
        'transferUs': clock.elapsedMicroseconds,
        'bytesPerSecond': clock.elapsedMicroseconds == 0 ? 0.0 :
            png.length * 1000000 / clock.elapsedMicroseconds,
      });
    }
  }

  Future<void> close() async {
    _closed = true;
    _wake();
    await _subscription?.cancel();
  }
}
