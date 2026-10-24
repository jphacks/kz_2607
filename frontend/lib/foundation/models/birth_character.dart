enum BirthStatus { egg, personalitySet, profileReady, born }

BirthStatus parseBirthStatus(dynamic raw) => switch (raw) {
  'egg' => BirthStatus.egg,
  'personality_set' => BirthStatus.personalitySet,
  'profile_ready' => BirthStatus.profileReady,
  'born' => BirthStatus.born,
  _ => throw const FormatException('birthStatusが未設定か未対応です。登録データの仕様を確認してください。'),
};

/// Shared shape for generateBirthProfile and pets/{petId}.birthProfile.
class BirthProfile {
  const BirthProfile({
    required this.source,
    required this.nameCandidates,
    required this.description,
    required this.firstPerson,
    required this.speechNote,
    required this.firstWords,
  });
  final String source, description, firstPerson, speechNote, firstWords;
  final List<String> nameCandidates;

  factory BirthProfile.fromMap(dynamic raw) {
    if (raw is! Map) throw const FormatException('誕生プロフィールがありません。');
    String text(String key) {
      final v = raw[key];
      if (v is! String || v.trim().isEmpty) {
        throw FormatException('$keyがありません。');
      }
      return v.trim();
    }

    final source = text('source');
    final firstPerson = text('firstPerson');
    final names = raw['nameCandidates'];
    if (!{'ai', 'template'}.contains(source) ||
        !{'ぼく', 'わたし', 'おれ', 'うち'}.contains(firstPerson) ||
        names is! List ||
        names.length != 3 ||
        names.any((n) => n is! String || n.trim().isEmpty)) {
      throw const FormatException('名前候補・一人称・生成元の形式が不正です。');
    }
    return BirthProfile(
      source: source,
      nameCandidates: List<String>.unmodifiable(
        names.cast<String>().map((n) => n.trim()),
      ),
      description: text('description'),
      firstPerson: firstPerson,
      speechNote: text('speechNote'),
      firstWords: text('firstWords'),
    );
  }
}

class BirthState {
  const BirthState({
    required this.status,
    required this.deviceId,
    required this.petId,
    required this.generation,
    this.name,
    this.profile,
  });
  final BirthStatus status;
  final String deviceId, petId;
  final int generation;
  final String? name;
  final BirthProfile? profile;
  factory BirthState.fromPet(Map<String, dynamic> data) {
    final status = parseBirthStatus(data['birthStatus']);
    if (data['deviceId'] is! String ||
        data['petId'] is! String ||
        (data['deviceId'] as String).isEmpty ||
        (data['petId'] as String).isEmpty ||
        data['generation'] is! int ||
        (data['generation'] as int) < 1) {
      throw const FormatException('getPetの応答形式を確認してください。');
    }
    return BirthState(
      status: status,
      deviceId: data['deviceId'] as String,
      petId: data['petId'] as String,
      generation: data['generation'] as int,
      name: data['name'] is String ? data['name'] as String : null,
      profile: status == BirthStatus.profileReady
          ? BirthProfile.fromMap(data['birthProfile'])
          : null,
    );
  }
}

class BirthConfirmation {
  const BirthConfirmation(this.name, this.firstWords);
  final String name;
  final String? firstWords;
}
