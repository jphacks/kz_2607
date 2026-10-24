import 'package:cloud_functions/cloud_functions.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';

/// Callable functions use the signed-in Firebase user's token automatically.
/// Only ping is wired here; registration and audio calls are separate steps.
class CloudFunctionsService {
  CloudFunctionsService({
    Future<void> Function()? prepare,
    Future<Object?> Function()? invokePing,
  }) : _prepare = prepare ?? _initializeAndAuthenticate,
       _invokePing = invokePing ?? _callPing;
  static const region = 'asia-northeast1';
  final Future<void> Function() _prepare;
  final Future<Object?> Function() _invokePing;

  static Future<void> _initializeAndAuthenticate() async {
    if (Firebase.apps.isEmpty) await Firebase.initializeApp();
    final auth = FirebaseAuth.instance;
    // Reuse the persisted session; never create a new UID for each request.
    if (auth.currentUser == null) await auth.signInAnonymously();
    if (auth.currentUser == null) {
      throw StateError('Firebaseにログインできませんでした');
    }
  }

  static Future<Object?> _callPing() async {
    final callable = FirebaseFunctions.instanceFor(region: region)
        .httpsCallable(
          'ping',
          options: HttpsCallableOptions(timeout: const Duration(seconds: 30)),
        );
    return (await callable.call<Object?>(<String, Object?>{})).data;
  }

  Future<void> ping() async {
    await _prepare();
    final result = await _invokePing();
    if (result is! Map || result['ok'] != true) {
      throw const FormatException('pingの応答が仕様と異なります（ok: true が必要です）');
    }
  }
}
