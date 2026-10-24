/// Display samples from Figma; these are not server-confirmed pets or owners.
class WatchPet {
  const WatchPet({
    required this.petId,
    required this.name,
    required this.summary,
    required this.sharedDays,
    required this.encounters,
  });
  final String petId, name, summary, sharedDays, encounters;

  static const firstCreatedSample = WatchPet(
    petId: 'sample-miro',
    name: 'ミロ',
    summary: '12人目の飼い主と / 更新：今日（表示例）',
    sharedDays: 'あなたが最初の飼い主として、この子を育てました。',
    encounters: '過去の家を巡った記録と、受け継いだ思い出。',
  );
}
