import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';

/// Provisional UUIDs shared with the reference prototype. Confirm with Core2.
class Core2Ble extends ChangeNotifier {
  static final serviceId = Guid('7f5a0001-7b7d-4f3b-9d01-000000000001');
  static final statusId = Guid('7f5a0001-7b7d-4f3b-9d01-000000000002');
  final Map<String, ScanResult> _results = {};
  final List<String> messages = [];
  final List<StreamSubscription<dynamic>> _subscriptions = [];
  StreamSubscription<List<int>>? _values;
  StreamSubscription<BluetoothConnectionState>? _connection;
  BluetoothDevice? device;
  bool scanning = false;
  bool busy = false;
  bool ready = false;
  bool _disposed = false;
  String status = '未接続';

  Core2Ble() {
    _subscriptions.add(
      FlutterBluePlus.onScanResults.listen((results) {
        for (final result in results) {
          // Use the advertised name, not a potentially stale cached name.
          final name = result.advertisementData.advName.toLowerCase();
          if (name.contains('m5stack')) {
            _results[result.device.remoteId.str] = result;
          } else {
            _results.remove(result.device.remoteId.str);
          }
        }
        _refresh();
      }, onError: (Object e) => _log('検索エラー: $e')),
    );
    _subscriptions.add(
      FlutterBluePlus.isScanning.listen((value) {
        scanning = value;
        if (!value && status == '検索中（15秒）') {
          status = '検索終了。結果からCore2を選んでください';
        }
        _refresh();
      }),
    );
    _subscriptions.add(
      FlutterBluePlus.adapterState.listen((state) {
        if (state == BluetoothAdapterState.off) {
          ready = false;
          status = 'Bluetoothを有効にしてください';
          _refresh();
        }
      }),
    );
  }

  List<ScanResult> get results =>
      _results.values.toList()..sort((a, b) => b.rssi.compareTo(a.rssi));

  void _refresh() {
    if (!_disposed) notifyListeners();
  }

  void _log(String message) {
    if (_disposed) return;
    messages.insert(
      0,
      '${DateTime.now().toIso8601String().substring(11, 19)} $message',
    );
    if (messages.length > 100) messages.removeLast();
    _refresh();
  }

  Future<void> scan() async {
    if (busy || scanning || device != null) return;
    busy = true;
    _refresh();
    try {
      if (!await FlutterBluePlus.isSupported) {
        throw StateError('BLE非対応です。Android実機で確認してください');
      }
      final adapter = await FlutterBluePlus.adapterState
          .where((s) => s != BluetoothAdapterState.unknown)
          .first
          .timeout(const Duration(seconds: 5));
      if (adapter != BluetoothAdapterState.on) await FlutterBluePlus.turnOn();
      _results.clear();
      status = '検索中（15秒）';
      // Filter advertised names in the scan listener (case insensitive).
      await FlutterBluePlus.startScan(timeout: const Duration(seconds: 15));
      _log('検索開始。近くのデバイス権限を許可してください');
    } catch (e) {
      status = '検索できません。権限・Bluetooth・位置情報設定を確認してください';
      _log('$e');
    } finally {
      busy = false;
      _refresh();
    }
  }

  Future<void> connect(BluetoothDevice target) async {
    if (busy || device != null) return;
    busy = true;
    status = '接続中';
    _refresh();
    try {
      await FlutterBluePlus.stopScan();
      await _connection?.cancel();
      _connection = null;
      device = target;
      await target.connect(
        license: License.nonprofit,
        timeout: const Duration(seconds: 15),
      );
      if (_disposed) {
        await target.disconnect();
        return;
      }
      _connection = target.connectionState.listen((state) {
        if (state == BluetoothConnectionState.disconnected) {
          ready = false;
          device = null;
          status = '切断されました';
          unawaited(_values?.cancel());
          _log('切断');
        }
      });
      final services = await target.discoverServices();
      BluetoothCharacteristic? characteristic;
      for (final service in services) {
        if (service.uuid != serviceId) continue;
        for (final value in service.characteristics) {
          if (value.uuid == statusId) characteristic = value;
        }
      }
      if (characteristic == null || !characteristic.properties.notify) {
        throw StateError('対象のNotify特性がありません。Core2側のUUID・実装を確認してください');
      }
      await _values?.cancel();
      _values = characteristic.onValueReceived.listen((bytes) {
        final hex = bytes
            .map((b) => b.toRadixString(16).padLeft(2, '0'))
            .join(' ');
        _log(
          'RX ${bytes.length} bytes: ${utf8.decode(bytes, allowMalformed: true)}\nHEX: $hex',
        );
      }, onError: (Object e) => _log('受信エラー: $e'));
      await characteristic.setNotifyValue(true);
      if (characteristic.properties.read) await characteristic.read();
      if (device != target) throw StateError('初期化中に切断されました');
      ready = true;
      status = '接続済み・受信待ち';
      _log('Notify購読開始');
    } catch (e) {
      _log('接続失敗: $e');
      await disconnect();
      status = '接続失敗。ログを確認してください';
    } finally {
      busy = false;
      _refresh();
    }
  }

  Future<void> disconnect() async {
    ready = false;
    final previous = device;
    device = null;
    await _values?.cancel();
    _values = null;
    await _connection?.cancel();
    _connection = null;
    try {
      await previous?.disconnect();
    } catch (e) {
      _log('切断エラー: $e');
    }
    status = '未接続';
    _refresh();
  }

  @override
  void dispose() {
    _disposed = true;
    for (final subscription in _subscriptions) {
      unawaited(subscription.cancel());
    }
    unawaited(FlutterBluePlus.stopScan().catchError((Object _) {}));
    unawaited(disconnect());
    super.dispose();
  }
}


