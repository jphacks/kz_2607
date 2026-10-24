/// Display samples from Figma; these are not server-confirmed pets or owners.
class WatchPet {
  const WatchPet({
    required this.petId,
    required this.name,
    required this.summary,
    required this.currentJourney,
    required this.sharedDays,
    required this.encounters,
  });
  final String petId, name, summary, currentJourney, sharedDays, encounters;

  static const samples = [
    WatchPet(
      petId: 'sample-miro',
      name: 'ミロ',
      summary: '12人目の飼い主と / 更新：今日（表示例）',
      currentJourney: '12人目の飼い主と',
      sharedDays: '7人目の飼い主として一緒に暮らしました。',
      encounters: '過去の家を巡った記録と、受け継いだ思い出。',
    ),
    WatchPet(
      petId: 'sample-popo',
      name: 'ポポ',
      summary: '新しい場所で旅を続けています（表示例）',
      currentJourney: '新しい場所で旅を続けています',
      sharedDays: 'あなたと一緒に過ごした日々の記録。',
      encounters: '過去の家を巡った記録と、受け継いだ思い出。',
    ),
  ];
}
