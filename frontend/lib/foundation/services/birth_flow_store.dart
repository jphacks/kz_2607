import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

class BirthFlowStore {
  BirthFlowStore(this.uid, this.petId);
  final String uid, petId;
  String get _key => 'birth_flow_v2_${uid}_$petId';
  Future<Map<String, dynamic>?> load() async {
    final raw = (await SharedPreferences.getInstance()).getString(_key);
    if (raw == null) return null;
    final data = jsonDecode(raw);
    if (data is! Map ||
        data['requestId'] is! String ||
        !RegExp(
          r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ).hasMatch(data['requestId'] as String) ||
        data['answers'] is! List ||
        (data['answers'] as List).length != 6 ||
        (data['answers'] as List).any(
          (v) => v != null && (v is! int || v < 0 || v > 3),
        )) {
      throw const FormatException('保存した誕生の回答を読み取れません。');
    }
    return Map<String, dynamic>.from(data);
  }

  Future<void> save(
    String requestId,
    List<int?> answers,
    String name, {
    bool initialPending = false,
    bool namePending = false,
  }) async {
    final ok = await (await SharedPreferences.getInstance()).setString(
      _key,
      jsonEncode({
        'requestId': requestId,
        'answers': answers,
        'name': name,
        'initialPending': initialPending,
        'namePending': namePending,
      }),
    );
    if (!ok) throw StateError('誕生の回答をスマホに保存できません。');
  }
}
