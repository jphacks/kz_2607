import 'dart:convert';
import 'dart:typed_data';
import 'voice_transfer.dart';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';

/// Callable functions use the signed-in Firebase user's token automatically.
/// Region and authentication are shared by registration and audio calls.
class CloudFunctionsService {
  CloudFunctionsService({
    Future<void> Function()? prepare,
    Future<Object?> Function(String, Map<String, Object?>, Duration)? invoke,
  }) : _prepare = prepare ?? _initializeAndAuthenticate,
       _invoke = invoke ?? _call;
  static const region = 'asia-northeast1';
  final Future<void> Function() _prepare;
  final Future<Object?> Function(String, Map<String, Object?>, Duration)
  _invoke;

  static Future<void> _initializeAndAuthenticate() async {
    if (Firebase.apps.isEmpty) await Firebase.initializeApp();
    final auth = FirebaseAuth.instance;
    // Reuse the persisted session; never create a new UID for each request.
    if (auth.currentUser == null) await auth.signInAnonymously();
    if (auth.currentUser == null) {
      throw StateError('Firebaseにログインできませんでした');
    }
  }

  static Future<Object?> _call(
    String name,
    Map<String, Object?> data,
    Duration timeout,
  ) async {
    return (await FirebaseFunctions.instanceFor(region: region)
            .httpsCallable(
              name,
              options: HttpsCallableOptions(timeout: timeout),
            )
            .call<Object?>(data))
        .data;
  }

  Future<String> registerDevice(String deviceId) async {
    if (!RegExp(r'^[A-Za-z0-9_.:\-]{1,64}$').hasMatch(deviceId)) {
      throw const FormatException('deviceIdは英数字と _ . : - の1〜64文字で指定してください');
    }
    await _prepare();
    final result = await _invoke('registerDevice', {
      'deviceId': deviceId,
    }, const Duration(seconds: 30));
    if (result is! Map ||
        result['deviceId'] != deviceId ||
        result['petId'] is! String ||
        (result['petId'] as String).isEmpty) {
      throw const FormatException('registerDeviceの応答が仕様と異なります');
    }
    return result['petId'] as String;
  }

  Future<Map<String, dynamic>> talkToPet({
    required String deviceId,
    required String petId,
    required Uint8List pcm,
  }) async {
    // Only PCM16/mono/16kHz from the BLE decoder is accepted here.
    final wav = voiceWav(pcm);
    await _prepare();
    final result = await _invoke('talkToPet', {
      'deviceId': deviceId,
      'petId': petId,
      'audioBase64': base64Encode(wav),
      'languageCode': 'ja-JP',
      'wantAudio': true,
      'replyFormat': 'ima_adpcm',
    }, const Duration(seconds: 130));
    // The deployed backend's no_speech response omits reply/audio fields.
    if (result is Map &&
        result['status'] == 'no_speech' &&
        result['petId'] == petId &&
        result['transcript'] is String) {
      return {
        'status': 'no_speech',
        'transcript': result['transcript'],
        'replyText': '',
        'audioStatus': 'skipped',
        'petId': petId,
        'learnedWords': <String>[],
      };
    }
    if (result is! Map ||
        !['ok', 'no_speech'].contains(result['status']) ||
        result['transcript'] is! String ||
        result['replyText'] is! String ||
        !['ok', 'failed', 'skipped'].contains(result['audioStatus']) ||
        result['petId'] != petId) {
      throw const FormatException('talkToPetの応答が仕様と異なります');
    }
    return Map<String, dynamic>.from(result);
  }
}
