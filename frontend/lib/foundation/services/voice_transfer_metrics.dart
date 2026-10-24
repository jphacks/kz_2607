import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';

/// Local JSONL measurements only; never stores audio, transcripts or credentials.
class VoiceTransferMetrics {
  Future<void> _pending = Future.value();
  static String get path =>
      '${Directory.systemTemp.path}/core2_voice/transfers.jsonl';

  void record(Map<String, Object?> metrics, void Function(String) log) {
    final line = jsonEncode({
      'schema': 1,
      'recordedAt': DateTime.now().toUtc().toIso8601String(),
      ...metrics,
    });
    debugPrint('BLE_METRIC $line');
    log('BLE計測: $line\n保存先: $path');
    _pending = _pending
        .then((_) async {
          final file = File(path);
          await file.parent.create(recursive: true);
          await file.writeAsString(
            '$line\n',
            mode: FileMode.append,
            flush: true,
          );
        })
        .catchError((Object error) {
          log('BLE計測の保存失敗: $error');
        });
  }
}
