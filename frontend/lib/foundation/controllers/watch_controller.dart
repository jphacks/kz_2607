import 'package:flutter/foundation.dart';
import 'package:cloud_functions/cloud_functions.dart';
import '../watch_pet.dart';
import '../services/cloud_functions_service.dart';

class WatchController extends ChangeNotifier {
  WatchController({CloudFunctionsService? api})
    : _api = api ?? CloudFunctionsService();
  final CloudFunctionsService _api;
  WatchPet? pet;
  bool loading = false, _disposed = false;
  String? error, diagnostic;

  Future<void> load() async {
    if (_disposed || loading) return;
    loading = true;
    pet = null;
    error = null;
    diagnostic = null;
    notifyListeners();
    try {
      final result = await _api.getFirstPet();
      if (!_disposed) pet = result;
    } on FirebaseFunctionsException catch (e) {
      if (_disposed) return;
      error = switch (e.code) {
        'unauthenticated' => 'ログイン状態を確認してください。',
        'permission-denied' => 'このアカウントでは最初の子の情報を確認できません。',
        'not-found' => '見守る情報を取得できませんでした。時間をおいて再試行してください。',
        _ => '見守る情報を取得できませんでした。通信状態を確認してください。',
      };
      final reason = e.details is Map ? (e.details as Map)['reason'] : null;
      diagnostic = 'getFirstPet / code: ${e.code} / reason: ${reason ?? "なし"}';
    } catch (e) {
      if (_disposed) return;
      error = e is FormatException
          ? '見守る情報の形式を確認できませんでした。'
          : '見守る情報を取得できませんでした。もう一度お試しください。';
      diagnostic = e is FormatException
          ? 'getFirstPet / reason: invalid_response'
          : null;
    } finally {
      if (!_disposed) {
        loading = false;
        notifyListeners();
      }
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
