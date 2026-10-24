import 'package:cloud_functions/cloud_functions.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import '../models/pet_letter.dart';
import '../services/cloud_functions_service.dart';

class LettersController extends ChangeNotifier {
  LettersController({CloudFunctionsService? api})
    : _api = api ?? CloudFunctionsService();
  final CloudFunctionsService _api;
  List<PetLetter> letters = const [];
  String? error;
  String? diagnostic;
  bool loading = false, _disposed = false;

  Future<void> load() async {
    if (_disposed || loading) return;
    loading = true;
    error = null;
    diagnostic = null;
    letters = const [];
    notifyListeners();
    try {
      final inbox = await _api.getLetters();
      if (_disposed) return;
      if (inbox.letters.isNotEmpty && inbox.firstPetId == null) {
        error = '最初の子の情報を確認できませんでした。しばらくしてから再試行してください。';
        diagnostic = 'getLetters / reason: first_pet_id_missing';
      } else {
        letters = List.unmodifiable(
          inbox.letters.where((letter) => letter.petId == inbox.firstPetId),
        );
      }
    } on FirebaseFunctionsException catch (e) {
      if (_disposed) return;
      final reason = e.details is Map ? (e.details as Map)['reason'] : null;
      final message = switch (e.code) {
        'unauthenticated' => 'ログイン状態を確認してください。',
        'permission-denied' => 'このアカウントでは手紙を取得できません。',
        _ => '手紙を取得できませんでした。通信状態を確認して、もう一度お試しください。',
      };
      error = message;
      diagnostic = 'getLetters / code: ${e.code} / reason: ${reason ?? "なし"}';
    } on FirebaseAuthException catch (e) {
      if (!_disposed) {
        error = 'ログインを確認してください。';
        diagnostic = '認証 / code: ${e.code}';
      }
    } catch (e) {
      if (!_disposed) {
        error = e is FormatException
            ? '手紙の情報を読み取れませんでした。'
            : '手紙を取得できませんでした。接続を確認して再試行してください。';
        diagnostic = e is FormatException
            ? 'getLetters / reason: invalid_response'
            : null;
      }
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
