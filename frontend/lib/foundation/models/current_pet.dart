import 'pet_appearance.dart';

class CurrentPet {
  const CurrentPet({
    required this.petId,
    required this.name,
    required this.generation,
    required this.gauge,
    required this.birthStatus,
    required this.description,
    required this.firstPerson,
    required this.speechNote,
    required this.learnedWords,
    this.createdAt,
    this.appearance,
  });
  final String petId, name, birthStatus, description, firstPerson, speechNote;
  final int generation;
  final double gauge;
  final DateTime? createdAt;
  final PetAppearance? appearance;
  final List<String> learnedWords;
  bool get born => birthStatus == 'born';

  factory CurrentPet.fromMap(Map<String, dynamic> data) {
    final id = data['petId'],
        generation = data['generation'],
        gauge = data['gauge'];
    if (id is! String ||
        id.isEmpty ||
        generation is! int ||
        generation < 1 ||
        gauge is! num ||
        !gauge.isFinite ||
        gauge < 0 ||
        gauge > 1) {
      throw const FormatException('getPetのペット情報・ゲージが不正です');
    }
    final profile = data['birthProfile'];
    String text(Object? value, String fallback) =>
        value is String && value.trim().isNotEmpty ? value.trim() : fallback;
    final rawWords = data['learnedWords'];
    if (rawWords != null &&
        (rawWords is! List || rawWords.any((word) => word is! String))) {
      throw const FormatException('getPetの覚えた言葉が不正です');
    }
    const traits = {
      'active': '活発',
      'affection': '人懐っこい',
      'talkative': 'おしゃべり',
      'logic': '考えることが好き',
      'curious': '好奇心旺盛',
      'night': '夜型',
    };
    return CurrentPet(
      appearance: data['appearance'] is Map
          ? PetAppearance.fromMap(data['appearance'] as Map)
          : null,
      petId: id,
      name: text(data['name'], '名前はこれから'),
      generation: generation,
      gauge: gauge.toDouble(),
      birthStatus: text(data['birthStatus'], 'unknown'),
      description: text(
        profile is Map ? profile['description'] : null,
        traits[data['birthTrait']] ?? '性格の紹介はまだありません',
      ),
      firstPerson: text(
        data['firstPerson'],
        profile is Map ? text(profile['firstPerson'], '未設定') : '未設定',
      ),
      speechNote: text(profile is Map ? profile['speechNote'] : null, '未設定'),
      learnedWords: List.unmodifiable(
        rawWords is List ? rawWords.cast<String>() : <String>[],
      ),
      createdAt: data['createdAt'] is String
          ? DateTime.tryParse(data['createdAt'] as String)
          : null,
    );
  }
}
