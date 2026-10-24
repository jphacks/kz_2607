/// Display samples from Figma; these are not server-confirmed pets or owners.
class WatchPet {
  const WatchPet({
    required this.petId,
    required this.name,
    required this.summary,
    required this.sharedDays,
    required this.encounters,
    this.currentGeneration = 1,
    this.memories = const [],
    this.isSample = false,
  });
  final String petId, name, summary, sharedDays, encounters;

  final int currentGeneration;
  final List<PetMemory> memories;
  final bool isSample;

  static const firstCreatedSample = WatchPet(
    currentGeneration: 12,
    isSample: true,
    memories: [
      PetMemory(
        generation: 1,
        title: 'はじめて名前を呼んだ日',
        body: 'ミロ、と呼びかけると、うれしそうに返事をしてくれました。あなたとの会話から、この子の旅がはじまりました。',
      ),
      PetMemory(
        generation: 1,
        title: 'おやすみの前に',
        body: '今日あったことを話して、一緒に一日を振り返りました。何気ない時間も、大切な思い出です。',
      ),
      PetMemory(
        generation: 2,
        title: '新しい場所でのごあいさつ',
        body: '次の飼い主との暮らしがはじまりました。少しずつ会話を重ねて、新しい言葉を覚えています。',
      ),
      PetMemory(
        generation: 12,
        title: '今日のうれしかったこと',
        body: 'いまの飼い主と、今日うれしかった出来事を話しました。またひとつ、思い出が増えました。',
      ),
    ],
    petId: 'sample-miro',
    name: 'ミロ',
    summary: '12人目の飼い主と / 更新：今日（表示例）',
    sharedDays: 'あなたが最初の飼い主として、この子を育てました。',
    encounters: '過去の家を巡った記録と、受け継いだ思い出。',
  );
}

/// One memory belonging to a specific owner generation.
class PetMemory {
  const PetMemory({
    required this.generation,
    required this.title,
    required this.body,
  });
  final int generation;
  final String title, body;
}
