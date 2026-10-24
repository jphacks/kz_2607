import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:cloud_functions/cloud_functions.dart';
import '../models/pending_exchange.dart';
import '../services/cloud_functions_service.dart';
import '../services/exchange_resolver.dart';

typedef SendExchangeResult =
    Future<void> Function(Map<String, dynamic> message);

/// Persist before reporting; keep terminal decisions until the Core2 application ACK.
class ExchangeController extends ChangeNotifier {
  ExchangeController(this.uid, {CloudFunctionsService? api})
      : _backend = api ?? CloudFunctionsService() {
    _ready = _restore();
  }
  final String uid;
  final CloudFunctionsService _backend;
  final Map<String, Map<String, dynamic>> _journal = {};
  late final Future<void> _ready;
  PendingExchange? candidate;
  String message = '交換候補はまだ届いていません。';
  bool busy = false;
  bool restoring = true;
  bool _ingesting = false;
  bool _disposed = false;
  bool _storageHealthy = true;
  String? _sessionDeviceId;
  String get _key => 'exchange_journal_v2_$uid';
  bool get hasUnresolved =>
      _journal.values.any((entry) => entry['acked'] != true);
  Future<void> get ready => _ready;
  String? deliveredPetId;

  void _publish() {
    if (!_disposed) notifyListeners();
  }

  Future<void> _save() async {
    final prefs = await SharedPreferences.getInstance();
    if (!await prefs.setString(_key, jsonEncode(_journal))) {
      throw StateError('交換情報を保存できません');
    }
  }

  Future<void> _restore() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_key);
      if (raw != null) {
        final data = jsonDecode(raw) as Map;
        for (final entry in data.entries) {
          final record = Map<String, dynamic>.from(entry.value as Map);
          PendingExchange.fromMap(
            Map<String, dynamic>.from(record['exchange'] as Map),
          );
          _journal[entry.key as String] = record;
        }
        final pending = _journal.values.where((e) => e['acked'] != true);
        if (pending.isNotEmpty) {
          candidate = PendingExchange.fromMap(
            Map<String, dynamic>.from(pending.first['exchange'] as Map),
          );
          message = '未完了の交換を復元しました。同じCore2に接続して結果を再確認してください。';
        }
      }
    } catch (error) {
      _storageHealthy = false;
      message = '交換履歴を復元できません。報告を止めています：$error';
    }
    restoring = false;
    _publish();
  }

  Future<bool> receive(Map<String, dynamic> data, String? ownDeviceId) async {
    if (_disposed || _ingesting) return false;
    _ingesting = true;
    try {
      await _ready;
      if (_disposed || !_storageHealthy) return false;
      final x = PendingExchange.fromMap(data);
      if (ownDeviceId == null || x.myDeviceId != ownDeviceId) {
        throw StateError('接続中のCore2と交換候補の端末が一致しません');
      }
      final old = _journal[x.transactionId];
      if (busy && old == null) return false;
      if (old != null) {
        final previous = PendingExchange.fromMap(
          Map<String, dynamic>.from(old['exchange'] as Map),
        );
        if (!previous.sameAs(x)) throw StateError('同じ交換IDに異なる内容が届きました');
        // An unfinished older exchange must not be hidden by a replay of a completed one.
        if (candidate != null &&
            candidate!.transactionId != x.transactionId &&
            hasUnresolved) {
          return false;
        }
      } else {
        if (hasUnresolved) throw StateError('未完了の交換があります。新しい交換は受け付けません');
        _journal[x.transactionId] = {
          'exchange': x.toMap(),
          'result': 'confirming',
          'acked': false,
        };
        try {
          await _save();
        } catch (_) {
          _journal.remove(x.transactionId);
          _storageHealthy = false;
          rethrow;
        }
      }
      candidate = x;
      _sessionDeviceId = ownDeviceId;
      message = '交換候補を保存しました。自動で交換を確認します。';
      return true;
    } catch (error) {
      message = '交換候補を保留しています：$error';
      return false;
    } finally {
      _ingesting = false;
      _publish();
    }
  }

  void connectedDevice(String? id) {
    _sessionDeviceId = id;
  }

  Future<void> process(SendExchangeResult send) async {
    if (_disposed || busy || _ingesting) return;
    deliveredPetId = null;
    busy = true;
    _publish();
    try {
      await _ready;
      final x = candidate;
      if (_disposed || !_storageHealthy || x == null) return;
      if (_sessionDeviceId != x.myDeviceId) {
        throw StateError('この交換のCore2に接続してください');
      }
      final record = _journal[x.transactionId]!;
      ExchangeDecision decision;
      final saved = record['result'];
      if ({'done', 'already_done', 'rejected'}.contains(saved)) {
        decision = ExchangeDecision(saved as String, '保存済みの確定結果を再送します');
      } else {
        // Durably record the original request before making any server mutation.
        record['acked'] = false;
        await _save();
        final resolver = ExchangeResolver((name, args) async {
          if (_disposed) throw StateError('ログインセッションが終了しました');
          try {
            return await _backend.callExchange(name, args);
          } on FirebaseFunctionsException catch (error) {
            final details = error.details;
            throw ExchangeApiError(error.code, error.message ?? error.code,
                reason: details is Map ? details['reason'] as String? : null);
          }
        });
        decision = await resolver.resolve(x);
        if (_disposed) return;
        record['result'] = decision.result;
        record['message'] = decision.message;
        await _save();
      }
      if (_disposed) return;
      if (decision.terminal) {
        final current = await _backend.registerDevice(x.myDeviceId);
        if (_disposed) return;
        final expected = decision.result == 'rejected'
            ? x.givenPetId
            : x.gotPetId;
        if (current != expected) {
          message = 'サーバーの現在のpetIdが交換結果と異なります。古い結果を適用せず担当者へ確認してください。';
          return;
        }
      }
      message = '${decision.message}。Core2へ結果を送信中…';
      _publish();
      await send({
        'type': 'exchange_result',
        'transactionId': x.transactionId,
        'result': decision.result,
        'givenPetId': x.givenPetId,
        'gotPetId': x.gotPetId,
      });
      if (_disposed) return;
      if (decision.terminal) {
        record['acked'] = true;
        await _save();
        deliveredPetId = decision.result == 'rejected'
            ? x.givenPetId
            : x.gotPetId;
        message = decision.result == 'rejected'
            ? '取消確定・Core2の受信確認済み'
            : '交換確定・Core2の受信確認済み';
      } else {
        message = '確認中です。Core2は変更せず、後で同じ交換を再確認してください。';
      }
    } catch (error) {
      if (!_disposed) message = '交換情報を保持しています。接続後に再確認してください：$error';
    } finally {
      busy = false;
      _publish();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
