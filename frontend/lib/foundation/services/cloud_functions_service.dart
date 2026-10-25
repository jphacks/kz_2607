import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'voice_transfer.dart';
import '../models/pet_letter.dart';
import '../watch_pet.dart';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:flutter/foundation.dart' show kDebugMode, debugPrint;
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';

/// Callable functions use the signed-in Firebase user's token automatically.
/// Region and authentication are shared by registration and audio calls.
class CloudFunctionsService {
  CloudFunctionsService({
    Future<void> Function()? prepare,
    Future<Object?> Function(String, Map<String, Object?>, Duration)? invoke,
    Future<Object?> Function(Map<String, Object?>)? progressFallback,
    Future<Object?> Function(Map<String, Object?>)? initialPersonalityFallback,
  }) : _prepare = prepare ?? _initializeAndAuthenticate,
       _invoke = invoke ?? _call,
       _progressFallback = progressFallback ?? _callProgressRaw,
       _initialPersonalityFallback =
           initialPersonalityFallback ??
           ((data) => _callJson('setInitialPersonality', data));
  static const region = 'asia-northeast1';
  final Future<void> Function() _prepare;
  final Future<Object?> Function(String, Map<String, Object?>, Duration)
  _invoke;
  final Future<Object?> Function(Map<String, Object?>) _progressFallback;
  final Future<Object?> Function(Map<String, Object?>)
  _initialPersonalityFallback;

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

  Future<Map<String, dynamic>> _birthCall(
    String name,
    Map<String, Object?> data, {
    Duration timeout = const Duration(seconds: 30),
  }) async {
    await _prepare();
    final result = await _invoke(name, data, timeout);
    if (result is! Map) throw FormatException('$nameの応答が仕様と異なります');
    return Map<String, dynamic>.from(result);
  }

  Future<Map<String, dynamic>> getPet(String deviceId) =>
      _birthCall('getPet', {'deviceId': deviceId});

  Future<Map<String, dynamic>> setInitialPersonality({
    required String deviceId,
    required List<int> answers,
    required String requestId,
  }) async {
    // Snapshot the request before any async work: retries must use identical answers.
    if (answers.length != 6 ||
        answers.any((answer) => answer < 0 || answer > 3)) {
      throw const FormatException('answers は0〜3の整数を6個指定してください。');
    }
    final data = <String, Object?>{
      'deviceId': deviceId,
      'answers': List<int>.unmodifiable(answers),
      'questionnaireVersion': 'birth_v1_6q4',
      'requestId': requestId,
    };
    if (kDebugMode) {
      debugPrint(
        'setInitialPersonality answers=${jsonEncode(data["answers"])} '
        'types=${answers.map((value) => value.runtimeType).join(",")} '
        'order=activity,friendly,talkative,logical,curious,nightowl',
      );
    }
    await _prepare();
    Object? result;
    try {
      result = await _invoke(
        'setInitialPersonality',
        data,
        const Duration(seconds: 30),
      );
    } on FirebaseFunctionsException catch (error) {
      final details = error.details;
      if (error.code != 'invalid-argument' ||
          details is! Map ||
          details['reason'] != 'invalid_answers') {
        rethrow;
      }
      // The native callable codec may wrap integers. Send JSON numbers directly
      // only after answer validation fails; keep the same idempotency identity.
      if (kDebugMode) {
        debugPrint(
          'setInitialPersonality: retry invalid_answers with JSON integers',
        );
      }
      result = await _initialPersonalityFallback(data);
    }
    if (result is! Map) {
      throw const FormatException('setInitialPersonalityの応答が仕様と異なります');
    }
    return Map<String, dynamic>.from(result);
  }

  Future<Map<String, dynamic>> generateBirthProfile(
    String petId, {
    bool regenerate = false,
  }) => _birthCall('generateBirthProfile', {
    'petId': petId,
    'regenerate': regenerate,
  }, timeout: const Duration(seconds: 25));

  Future<Map<String, dynamic>> setPetName({
    required String deviceId,
    required String name,
    required String firstPerson,
  }) => _birthCall('setPetName', {
    'deviceId': deviceId,
    'name': name,
    'firstPerson': firstPerson,
  });

  Future<WatchPet?> getFirstPet() async {
    await _prepare();
    final response = await _invoke(
      'getFirstPet',
      {},
      const Duration(seconds: 30),
    );
    if (response is! Map) throw const FormatException('getFirstPetの応答形式が不正です');
    return WatchPet.fromResponse(response);
  }

  Future<LettersInbox> getLetters() async {
    await _prepare();
    final result = await _invoke('getLetters', {}, const Duration(seconds: 30));
    if (result is! Map ||
        result['letters'] is! List ||
        (result['firstPetId'] != null &&
            (result['firstPetId'] is! String ||
                (result['firstPetId'] as String).trim().isEmpty))) {
      throw const FormatException('getLettersの応答が仕様と異なります');
    }
    final letters = (result['letters'] as List).map((item) {
      if (item is! Map) throw const FormatException('手紙の形式が不正です');
      return PetLetter.fromMap(item);
    }).toList()..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return LettersInbox(
      firstPetId: result['firstPetId'] as String?,
      letters: letters,
    );
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

  Future<void> recordProgress({
    required String deviceId,
    required String date,
    required int steps,
  }) async {
    if (steps < 0 || steps > 200000) {
      throw RangeError.range(steps, 0, 200000, 'steps');
    }
    await _prepare();
    final data = <String, Object?>{
      'deviceId': deviceId,
      'date': date,
      'steps': steps,
    };
    Object? result;
    try {
      result = await _invoke(
        'recordProgress',
        data,
        const Duration(seconds: 30),
      );
    } on FirebaseFunctionsException catch (error) {
      if (error.code != 'invalid-argument' ||
          !(error.message ?? '').contains('steps')) {
        rethrow;
      }
      // Some native callable codecs send Dart int as a protobuf Int64Value.
      // A direct callable request preserves this bounded value as a JSON int.
      result = await _progressFallback(data);
    }
    if (result is! Map || result['status'] != 'ok' || result['date'] != date) {
      throw const FormatException('recordProgressの応答が仕様と異なります');
    }
  }

  static Future<Object?> _callProgressRaw(Map<String, Object?> data) =>
      _callJson('recordProgress', data);

  static Future<Object?> _callJson(
    String function,
    Map<String, Object?> data,
  ) async {
    final token = await FirebaseAuth.instance.currentUser?.getIdToken();
    if (token == null || token.isEmpty) {
      throw StateError('$functionの呼び出しにはFirebaseログインが必要です');
    }
    final projectId = Firebase.app().options.projectId;
    final uri = Uri.https(
      '$region-$projectId.cloudfunctions.net',
      '/$function',
    );
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 10);
    try {
      final request = await client
          .postUrl(uri)
          .timeout(const Duration(seconds: 30));
      request.headers.contentType = ContentType.json;
      request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
      final payload = utf8.encode(jsonEncode({'data': data}));
      request.contentLength = payload.length;
      request.add(payload);
      final response = await request.close().timeout(
        const Duration(seconds: 30),
      );
      final body = await utf8.decoder
          .bind(response)
          .join()
          .timeout(const Duration(seconds: 30));
      final decoded = jsonDecode(body);
      if (decoded is! Map) {
        throw FormatException('$functionの応答が不正です');
      }
      final error = decoded['error'];
      if (error is Map) {
        throw FirebaseFunctionsException(
          code: (error['status']?.toString() ?? 'unknown')
              .toLowerCase()
              .replaceAll('_', '-'),
          message: error['message']?.toString() ?? '$functionの呼び出しに失敗しました。',
          details: error['details'],
        );
      }
      return decoded['result'] ?? decoded['data'];
    } finally {
      client.close(force: true);
    }
  }

  /// Exchange callables use the same Firebase session and region as voice calls.
  Future<Map<String, dynamic>> callExchange(
    String name,
    Map<String, dynamic> arguments,
  ) async {
    if (!{
      'reportExchange',
      'getExchangeResult',
      'cancelExchange',
    }.contains(name)) {
      throw ArgumentError.value(name, 'name');
    }
    await _prepare();
    final result = await _invoke(name, arguments, const Duration(seconds: 30));
    if (result is! Map) {
      throw FormatException('$nameの応答が仕様と異なります');
    }
    return Map<String, dynamic>.from(result);
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
