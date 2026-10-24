import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'voice_transfer.dart';

class VoiceLink {
  VoiceLink(
    this.data,
    this.control, {
    required this.onStatus,
    required this.onProgress,
    required this.onAudio,
    this.onMetrics,
  });
  final BluetoothCharacteristic data, control;
  final void Function(Map<String, Object?>)? onMetrics;
  final void Function(String) onStatus;
  final void Function(int, int) onProgress;
  final void Function(Uint8List) onAudio;
  StreamSubscription<List<int>>? _subscription;
  Timer? _timer;
  VoiceTransfer? _transfer;
  Future<void> _writes = Future.value();
  bool _closed = false;

  Future<void> start(BluetoothDevice device) async {
    var chunk = (device.mtuNow - 7).clamp(1, 240);
    try {
      chunk = ((await device.requestMtu(247)) - 7).clamp(1, 240);
    } catch (_) {
      chunk = (device.mtuNow - 7).clamp(1, 240);
    }
    if (_closed) return;
    _transfer = VoiceTransfer(
      chunkSize: chunk,
      ack: _ack,
      onProgress: onProgress,
      onAudio: onAudio,
      onMetrics: (metrics) =>
          onMetrics?.call({...metrics, 'mtu': device.mtuNow}),
    );
    _subscription = data.onValueReceived.listen((packet) {
      if (_closed) return;
      try {
        _transfer!.receive(packet);
        _timer?.cancel();
        if (_transfer!.active) {
          _timer = Timer(const Duration(seconds: 15), () {
            _transfer!.reset();
            onStatus('音声転送がタイムアウトしました。Core2で再録音してください');
          });
        }
      } catch (e) {
        _fail('音声受信失敗: $e');
      }
    }, onError: (Object e) => _fail('音声通知エラー: $e'));
    await data.setNotifyValue(true);
    if (_closed) return;
    await control.write([1, chunk], withoutResponse: false);
    if (!_closed) onStatus('音声受信準備完了。Core2で録音してください');
  }

  void _ack(int session, int sequence) {
    _writes = _writes
        .then<void>((_) async {
          if (_closed) return;
          await control.write([
            2,
            session,
            sequence & 255,
            sequence >> 8,
          ], withoutResponse: control.properties.writeWithoutResponse);
        })
        .catchError((Object e) => _fail('音声ACK送信失敗: $e'));
  }

  void _fail(String message) {
    if (_closed) return;
    _timer?.cancel();
    _transfer?.reset();
    onStatus(message);
  }

  Future<void> close() async {
    _closed = true;
    _timer?.cancel();
    _transfer?.reset();
    await _subscription?.cancel();
  }
}
