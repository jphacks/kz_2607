import 'package:flutter/foundation.dart';
import 'package:cloud_functions/cloud_functions.dart';
import '../models/current_pet.dart';
import '../services/cloud_functions_service.dart';

class HomePetController extends ChangeNotifier {
  HomePetController({CloudFunctionsService? api})
    : _api = api ?? CloudFunctionsService();
  final CloudFunctionsService _api;
  CurrentPet? pet;
  String? error, diagnostic;
  String? _deviceId, _petId;
  bool loading = false, _disposed = false;
  int _epoch = 0;
  bool _refreshRequested = false;

  bool bind(String? deviceId, String? petId) {
    if (deviceId == _deviceId && petId == _petId) return false;
    _deviceId = deviceId;
    _petId = petId;
    _epoch++;
    _refreshRequested = false;
    pet = null;
    error = null;
    diagnostic = null;
    loading = false;
    if (deviceId != null && petId != null) {
      refresh();
    } else {
      notifyListeners();
    }
    return true;
  }

  Future<void> refresh() async {
    if (_disposed || _deviceId == null || _petId == null) return;
    if (loading) {
      _refreshRequested = true;
      return;
    }
    final epoch = _epoch, device = _deviceId!, expectedPet = _petId!;
    loading = true;
    error = null;
    diagnostic = null;
    notifyListeners();
    try {
      final data = await _api.getPet(device);
      if (_disposed || epoch != _epoch) return;
      if (data['deviceId'] != device || data['petId'] != expectedPet) {
        pet = null;
        throw const FormatException('端末のペットが変わりました。M5に再接続してください。');
      }
      pet = CurrentPet.fromMap(data);
    } on FirebaseFunctionsException catch (e) {
      if (_disposed || epoch != _epoch) return;
      pet = null;
      error = e.code == 'permission-denied'
          ? 'このアカウントでは端末の情報を取得できません。'
          : 'ペット情報を取得できませんでした。';
      final reason = e.details is Map ? (e.details as Map)['reason'] : null;
      diagnostic = 'getPet / code: ${e.code} / reason: ${reason ?? "なし"}';
    } catch (e) {
      if (_disposed || epoch != _epoch) return;
      pet = null;
      error = e is FormatException
          ? e.message
          : 'ペット情報を取得できませんでした。通信状態を確認してください。';
    } finally {
      if (!_disposed && epoch == _epoch) {
        loading = false;
        notifyListeners();
        if (_refreshRequested) {
          _refreshRequested = false;
          await refresh();
        }
      }
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _epoch++;
    super.dispose();
  }
}
