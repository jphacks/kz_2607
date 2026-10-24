import 'package:flutter/material.dart';
import 'designsystem/app_card.dart';
import 'designsystem/pet_portrait.dart';
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

  String get _description => switch (stage) {
    JourneyStage.beginning => pet.sharedDays,
    JourneyStage.memories => pet.encounters,
    JourneyStage.present => pet.summary.replaceAll(' / ', '\n'),
  };

  String get _note => switch (stage) {
    JourneyStage.beginning => '最初の出会いは、ずっとこの子の旅のはじまりです。',
    JourneyStage.memories => '飼い主から次の飼い主へ。この子がつないできた出会いを振り返ります。',
    JourneyStage.present => '新しい場所でも、この子らしい毎日を重ねています。',
  };

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
              Center(child: PetPortrait(name: pet.name, size: 152)),
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
              AppCard(
                padding: 24,
                radius: 24,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(stage.icon, color: AppColors.primary, size: 28),
                    const SizedBox(height: 16),
                    Text(
                      stage.title,
                      style: const TextStyle(
                        fontSize: 20,
                        height: 1.5,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 18),
                    Text(
                      _description,
                      style: const TextStyle(fontSize: 15, height: 1.9),
                    ),
                    const SizedBox(height: 20),
                    const Divider(color: AppColors.soft),
                    const SizedBox(height: 12),
                    Text(
                      _note,
                      style: const TextStyle(
                        color: AppColors.muted,
                        fontSize: 13,
                        height: 1.8,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              const Text(
                '表示サンプルです。実際の日時や出会いの履歴は、まだ連携されていません。',
                style: TextStyle(
                  fontSize: 12,
                  height: 1.7,
                  color: AppColors.muted,
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

