import 'package:flutter/material.dart';
import 'designsystem/app_card.dart';
import 'designsystem/current_pet_portrait.dart';
import 'foundation/app_colors.dart';
import 'foundation/watch_pet.dart';

enum JourneyStage {
  beginning('はじまり', 'あなたとはじまった旅', Icons.home_outlined),
  memories('つながる思い出', '出会いが、思い出になっていく', Icons.route_outlined),
  present('いま', '離れていても、旅はつづく', Icons.explore_outlined);

  const JourneyStage(this.label, this.title, this.icon);
  final String label, title;
  final IconData icon;
}

class JourneyDetailScreen extends StatelessWidget {
  const JourneyDetailScreen({
    super.key,
    required this.pet,
    required this.stage,
  });
  final WatchPet pet;
  final JourneyStage stage;

  List<int> get _generations {
    if (stage == JourneyStage.beginning) return [1];
    if (stage == JourneyStage.present) return [pet.currentGeneration];
    final generations =
        pet.memories
            .map((memory) => memory.generation)
            .where(
              (generation) =>
                  generation >= 2 && generation < pet.currentGeneration,
            )
            .toSet()
            .toList()
          ..sort();
    return generations;
  }

  String get _introduction => switch (stage) {
    JourneyStage.beginning => 'あなたと${pet.name}が過ごした、はじまりの思い出。',
    JourneyStage.memories => '2代目から今のひとつ前の代まで、受け継がれてきた思い出。',
    JourneyStage.present => 'いまの飼い主と${pet.name}が重ねている思い出。',
  };

  Widget _generationMemories(int generation) {
    final memories = pet.memories.where(
      (memory) => memory.generation == generation,
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: AppCard(
        padding: 24,
        radius: 24,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              generation == 1 ? 'あなたとの思い出' : '$generation代目の思い出',
              style: const TextStyle(
                fontSize: 19,
                height: 1.5,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              generation == pet.currentGeneration
                  ? '現在の飼い主との記録'
                  : '一緒に過ごした日々の記録',
              style: const TextStyle(color: AppColors.primary, fontSize: 12),
            ),
            if (memories.isEmpty) ...[
              const SizedBox(height: 20),
              const Text(
                'まだ思い出の記録がありません。',
                style: TextStyle(color: AppColors.muted, height: 1.7),
              ),
            ],
            for (final memory in memories) ...[
              const SizedBox(height: 20),
              const Divider(color: AppColors.soft),
              const SizedBox(height: 16),
              Text(
                memory.title,
                style: const TextStyle(
                  fontSize: 16,
                  height: 1.6,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 10),
              Text(
                memory.body,
                style: const TextStyle(fontSize: 14, height: 1.9),
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: AppColors.background,
    appBar: AppBar(
      title: Text(stage.label),
      backgroundColor: AppColors.background,
      foregroundColor: AppColors.text,
      surfaceTintColor: Colors.transparent,
    ),
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(24, 12, 24, 32),
            children: [
              Center(
                child: CurrentPetPortrait(
                  name: pet.name,
                  appearance: pet.appearance,
                  size: 152,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                pet.name,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                '最初に生まれた子',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.primary, fontSize: 12),
              ),
              const SizedBox(height: 28),
              Text(
                _introduction,
                style: const TextStyle(
                  fontSize: 15,
                  height: 1.8,
                  color: AppColors.muted,
                ),
              ),
              const SizedBox(height: 20),
              if (_generations.isEmpty)
                const AppCard(
                  padding: 24,
                  radius: 24,
                  child: Text('2代目から今のひとつ前の代までの思い出は、まだ記録されていません。'),
                ),
              for (final generation in _generations)
                _generationMemories(generation),
              const SizedBox(height: 20),
            ],
          ),
        ),
      ),
    ),
  );
}
