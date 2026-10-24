import '../models/birth_character.dart';
import '../models/birth_questionnaire.dart';
import 'cloud_functions_service.dart';

class BirthService {
  BirthService({CloudFunctionsService? api})
    : _api = api ?? CloudFunctionsService();
  final CloudFunctionsService _api;

  Future<BirthState> load({
    required String petId,
    required String deviceId,
  }) async {
    final state = BirthState.fromPet(await _api.getPet(deviceId));
    if (state.deviceId != deviceId || state.petId != petId) {
      throw StateError('端末のペットが変わりました。ホームで再接続してください。');
    }
    return state;
  }

  Future<void> setInitial({
    required String deviceId,
    required String petId,
    required String requestId,
    required BirthAnswers answers,
  }) async {
    await load(petId: petId, deviceId: deviceId);
    final result = await _api.setInitialPersonality(
      deviceId: deviceId,
      answers: answers.apiAnswers,
      requestId: requestId,
    );
    if (result['status'] != 'ok' ||
        result['petId'] != petId ||
        !{
          'personality_set',
          'profile_ready',
          'born',
        }.contains(result['birthStatus'])) {
      throw const FormatException('初期性格の保存結果が一致しません。保存状態を再確認してください。');
    }
  }

  Future<BirthProfile> generate({
    required String petId,
    bool regenerate = false,
  }) async {
    final data = await _api.generateBirthProfile(petId, regenerate: regenerate);
    if (data['status'] != 'ok' ||
        data['petId'] != petId ||
        data['birthStatus'] != 'profile_ready') {
      throw const FormatException('generateBirthProfileの応答形式が不正です。');
    }
    return BirthProfile.fromMap(data);
  }

  Future<BirthConfirmation> confirm({
    required String deviceId,
    required String petId,
    required String name,
    required String firstPerson,
  }) async {
    final trimmed = name.trim();
    if (trimmed.isEmpty ||
        trimmed.runes.length > 12 ||
        RegExp(r'[\x00-\x1f\x7f]').hasMatch(trimmed)) {
      throw const FormatException('名前は改行を含まない1〜12文字で入力してください。');
    }
    if (!{'ぼく', 'わたし', 'おれ', 'うち'}.contains(firstPerson)) {
      throw const FormatException('一人称の形式が不正です。');
    }
    await load(petId: petId, deviceId: deviceId);
    final data = await _api.setPetName(
      deviceId: deviceId,
      name: trimmed,
      firstPerson: firstPerson,
    );
    if (data['petId'] != petId ||
        data['birthStatus'] != 'born' ||
        data['name'] != trimmed ||
        data['firstPerson'] != firstPerson ||
        (data['firstWords'] != null && data['firstWords'] is! String)) {
      throw const FormatException('誕生の確定結果が一致しません。保存状態を再確認してください。');
    }
    return BirthConfirmation(trimmed, data['firstWords'] as String?);
  }
}
