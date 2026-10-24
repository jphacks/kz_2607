import 'dart:async';
import 'dart:convert';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'cloud_functions_service.dart';

/// Explicitly binds uploads to the BLE connection the user has confirmed.
class VoiceCloudService extends ChangeNotifier {
  VoiceCloudService({CloudFunctionsService? api})
    : _api = api ?? CloudFunctionsService();
  final CloudFunctionsService _api;
  String? _connection, deviceId, petId;
  String status = '音声送信は無効です';
  String? transcript, replyText;
  Uint8List? replyAudio;
  Stopwatch? _replyClock;
  int get cloudReplyElapsedUs => _replyClock?.elapsedMicroseconds ?? 0;
  Future<void> Function(Uint8List bytes, int sampleCount)? sendReply;
  void Function()? cancelReply;
  bool _transferringReply = false;
  String? replyTransferStatus;
  int replySentBytes = 0, replyTotalBytes = 0;
  bool get canSendReply => sendReply != null;
  List<String> learnedWords = [];
  bool _busy = false, _disposed = false;
  int _epoch = 0;
  bool _autoEnable = false;
  bool get busy => _busy;
  bool get enabled => deviceId != null && petId != null && _connection != null;
  bool get connected => _connection != null;
  String? get connectionDeviceId {
    final address = _connection;
    if (address == null ||
        !RegExp(r'^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$').hasMatch(address)) {
      return null;
    }
    return address.replaceAll(':', '').toUpperCase();
  }

  void _publish() {
    if (!_disposed) notifyListeners();
  }

  void setConnection(String? connection) {
    if (_connection == connection) return;
    _connection = connection;
    disable();
  }

  void disable() {
    _autoEnable = false;
    _epoch++;
    if (_transferringReply) cancelReply?.call();
    replyTransferStatus = null;
    replySentBytes = replyTotalBytes = 0;
    deviceId = petId = null;
    transcript = replyText = null;
    replyAudio = null;
    learnedWords = [];
    status = '音声中継は停止中です。M5Stackへの接続後に自動で準備します';
    _publish();
  }

  // Called after the user selects a Core2 and BLE setup has completed.
  void startForConnection(String connection) {
    if (_disposed) return;
    setConnection(connection);
    _autoEnable = true;
    _resumeAutoEnable();
  }

  void _resumeAutoEnable() {
    if (_disposed || !_autoEnable || _busy || !connected || enabled) return;
    _autoEnable = false;
    unawaited(enable());
  }

  Future<void> enable() async {
    if (_busy || !connected || _disposed || enabled) return;
    final id = connectionDeviceId;
    if (id == null) {
      status = '接続先のBLE MACを取得できないため、端末登録は行いません';
      _publish();
      return;
    }
    final epoch = _epoch;
    _busy = true;
    status = 'registerDevice：端末を登録・確認中…';
    _publish();
    try {
      final pet = await _api.registerDevice(id.trim());
      if (_disposed || epoch != _epoch) return;
      deviceId = id.trim();
      petId = pet;
      status = '音声送信を有効にしました。次の録音から自動送信します';
    } catch (e) {
      if (!_disposed && epoch == _epoch) {
        status = _error('registerDevice', e, attemptedId: id.trim());
      }
    } finally {
      _busy = false;
      _publish();
      _resumeAutoEnable();
    }
  }

  Future<void> sendPcm(Uint8List pcm) async {
    // Never queue recordings made before confirmation, or during another call.
    if (!enabled || _busy || _disposed) return;
    final epoch = _epoch;
    final id = deviceId!, pet = petId!;
    _busy = true;
    transcript = replyText = null;
    replyAudio = null;
    learnedWords = [];
    replyTransferStatus = null;
    replySentBytes = replyTotalBytes = 0;
    status = 'talkToPet：音声送信・返答待ち…（送信中の新しい録音は送信しません）';
    _publish();
    try {
      final result = await _api.talkToPet(deviceId: id, petId: pet, pcm: pcm);
      _replyClock = Stopwatch()..start();
      if (_disposed || epoch != _epoch) return;
      transcript = result['transcript'] as String;
      replyText = result['replyText'] as String;
      final words = result['learnedWords'];
      if (words is List) learnedWords = words.whereType<String>().toList();
      if (result['status'] == 'no_speech') {
        status = '声を聞き取れませんでした。Core2で録音し直してください';
      } else if (result['audioStatus'] == 'ok') {
        final audio = result['replyAudioBase64'];
        if (audio is! String || audio.isEmpty) {
          throw const FormatException('返答音声がありません');
        }
        replyAudio = base64Decode(audio);
        if (replyAudio!.isEmpty) throw const FormatException('返答音声が空です');
        status = '返答文と音声を受信しました';
        final meta = result['replyAudio'];
        if (meta is! Map ||
            meta['format'] != 'ima_adpcm' ||
            meta['sampleRate'] != 16000 ||
            meta['channels'] != 1 ||
            meta['sampleCount'] is! int ||
            (meta['sampleCount'] as int) < 1 ||
            (meta['sampleCount'] as int) > 480000 ||
            replyAudio!.length != ((meta['sampleCount'] as int) + 1) ~/ 2) {
          throw const FormatException('Core2向け返答音声の形式・データ長が不正です');
        }
        final sender = sendReply;
        if (sender == null) {
          replyTransferStatus = 'Core2側に返答音声の受信サービスがありません';
        } else {
          _transferringReply = true;
          replyTransferStatus = 'Core2へ返答音声を転送中…';
          _publish();
          try {
            await sender(replyAudio!, meta['sampleCount'] as int);
            if (_disposed || epoch != _epoch) return;
            replyTransferStatus = 'Core2の音声受信完了ACKを確認しました';
          } catch (e) {
            if (_disposed || epoch != _epoch) return;
            replyTransferStatus = 'Core2への返答音声転送に失敗: $e';
          } finally {
            _transferringReply = false;
          }
        }
      } else {
        status = result['audioStatus'] == 'failed'
            ? '返答文を受信しました。返答音声の生成には失敗しました'
            : '返答文を受信しました（返答音声なし）';
      }
    } catch (e) {
      if (_disposed || epoch != _epoch) return;
      if (e is FirebaseFunctionsException &&
          e.details is Map &&
          (e.details as Map)['reason'] == 'pet_changed') {
        disable();
        status =
            '${_error('talkToPet', e)}\nペットが変わったため会話を破棄しました。M5Stackに再接続してください';
      } else {
        status = _error('talkToPet', e);
      }
      // No automatic retry: an ambiguous failure could duplicate a conversation.
    } finally {
      _replyClock?.stop();
      _busy = false;
      _publish();
      _resumeAutoEnable();
    }
  }

  void replyProgress(int sent, int total) {
    if (_disposed || !_transferringReply) return;
    replySentBytes = sent;
    replyTotalBytes = total;
    _publish();
  }

  String _error(String function, Object error, {String? attemptedId}) {
    if (error is FirebaseFunctionsException) {
      final details = error.details;
      final reason = details is Map ? details['reason'] : null;
      final retry = details is Map ? details['retryAfterSec'] : null;
      if (error.code == 'permission-denied') {
        return '$function 失敗 / deviceId: ${attemptedId ?? deviceId ?? "登録前"}\n'
            'code: ${error.code}\nreason: ${reason ?? "なし"}\n'
            'この端末は現在のアカウントでは利用できません。'
            'ログイン先を変更した場合は、端末を登録したアカウントか確認してください。';
      }
      return '$function 失敗 / deviceId: ${attemptedId ?? deviceId ?? "登録前"}\ncode: ${error.code}\nreason: ${reason ?? "なし"}${retry == null ? "" : "\n$retry秒後に録音し直してください"}';
    }
    if (error is FirebaseAuthException) {
      return '$function 認証失敗\ncode: ${error.code}';
    }
    return '$function 失敗: $error';
  }

  @override
  void dispose() {
    _disposed = true;
    _epoch++;
    if (_transferringReply) cancelReply?.call();
    super.dispose();
  }
}
