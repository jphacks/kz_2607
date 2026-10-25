import 'models/pet_appearance.dart';

/// The authenticated user's first-created pet, returned by getFirstPet.
class WatchPet {
  const WatchPet({
    required this.petId,
    required this.name,
    required this.currentGeneration,
    required this.withYou,
    required this.appearance,
    required this.memories,
  });
  final String petId, name;
  final int currentGeneration;
  final bool withYou;
  final PetAppearance appearance;
  final List<PetMemory> memories;
  String get summary => withYou
      ? 'いまはあなたと一緒 / 現在 $currentGeneration代目'
      : '現在 $currentGeneration代目の飼い主と一緒';
  String get sharedDays =>
      'あなたとの思い出 ${memories.where((memory) => memory.generation == 1).length}件';
  String get encounters => '受け継がれた思い出を、世代ごとに振り返ります。';

  static WatchPet? fromResponse(Map data) {
    if (!data.containsKey('petId') ||
        data['memories'] is! List ||
        data['withYou'] is! bool) {
      throw const FormatException('getFirstPetの応答形式が不正です');
    }
    if (data['petId'] == null) {
      if ((data['memories'] as List).isNotEmpty || data['withYou'] != false) {
        throw const FormatException('最初のペットの空状態が不正です');
      }
      return null;
    }
    final id = data['petId'],
        generation = data['generation'],
        name = data['name'];
    if (id is! String ||
        id.isEmpty ||
        generation is! int ||
        generation < 1 ||
        (name != null && name is! String) ||
        data['appearance'] is! Map) {
      throw const FormatException('最初のペット情報が不正です');
    }
    final appearance = PetAppearance.fromMap(data['appearance'] as Map);
    if (data['stage'] != appearance.stage) {
      throw const FormatException('成長段階が一致しません');
    }
    final memories = <PetMemory>[];
    final generations = <int>{};
    for (final group in data['memories'] as List) {
      if (group is! Map ||
          group['generation'] is! int ||
          group['mine'] is! bool ||
          group['items'] is! List) {
        throw const FormatException('世代別の思い出が不正です');
      }
      final g = group['generation'] as int;
      if (g < 1 || g > generation || !generations.add(g)) {
        throw const FormatException('思い出の世代が不正です');
      }
      for (final item in group['items'] as List) {
        if (item is! Map ||
            item['text'] is! String ||
            (item['text'] as String).trim().isEmpty) {
          throw const FormatException('思い出の本文が不正です');
        }
        final rawDate = item['createdAt'];
        final date = rawDate is String ? DateTime.tryParse(rawDate) : null;
        if (rawDate != null && date == null) {
          throw const FormatException('思い出の日付が不正です');
        }
        memories.add(
          PetMemory(
            generation: g,
            body: item['text'] as String,
            createdAt: date,
            mine: group['mine'] as bool,
          ),
        );
      }
    }
    memories.sort((a, b) {
      final order = a.generation.compareTo(b.generation);
      if (order != 0) return order;
      if (a.createdAt == null) return b.createdAt == null ? 0 : 1;
      return b.createdAt == null ? -1 : b.createdAt!.compareTo(a.createdAt!);
    });
    return WatchPet(
      petId: id,
      name: name is String && name.trim().isNotEmpty ? name : '名前はこれから',
      currentGeneration: generation,
      withYou: data['withYou'] as bool,
      appearance: appearance,
      memories: List.unmodifiable(memories),
    );
  }
}

class PetMemory {
  const PetMemory({
    required this.generation,
    required this.body,
    required this.mine,
    this.createdAt,
  });
  final int generation;
  final String body;
  final bool mine;
  final DateTime? createdAt;
  String get title {
    final day = createdAt?.toLocal();
    return day == null ? '思い出' : '${day.year}年${day.month}月${day.day}日の思い出';
  }
}
