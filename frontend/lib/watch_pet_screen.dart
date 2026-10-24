import 'package:flutter/material.dart';
import 'designsystem/action_button.dart';
import 'designsystem/watch_information_card.dart';
import 'foundation/app_colors.dart';
import 'foundation/watch_pet.dart';

class WatchPetScreen extends StatelessWidget {
  const WatchPetScreen({super.key, required this.pet});
  final WatchPet pet;
  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              const Text(
                '見守る',
                style: TextStyle(
                  fontSize: 11,
                  height: 1.5,
                  color: AppColors.muted,
                ),
              ),
              const SizedBox(height: 14),
              Text(
                '${pet.name}の旅',
                style: const TextStyle(
                  fontSize: 24,
                  height: 1.5,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 14),
              const Text(
                '見守り中のペットの履歴',
                style: TextStyle(
                  fontSize: 14,
                  height: 1.5,
                  color: AppColors.muted,
                ),
              ),
              const SizedBox(height: 14),
              WatchInformationCard(
                title: pet.currentJourney,
                body: '現在 / 新しい場所で旅を続けています。',
                highlighted: true,
              ),
              const SizedBox(height: 14),
              WatchInformationCard(title: 'あなたと過ごした日々', body: pet.sharedDays),
              const SizedBox(height: 14),
              WatchInformationCard(title: 'これまでの出会い', body: pet.encounters),
              const SizedBox(height: 14),
              const Text(
                '匿名の飼い主・公開可能な成長記録を表示。個人的な会話を履歴に出しません。表示データはサンプルです。',
                style: TextStyle(
                  fontSize: 12,
                  height: 1.5,
                  color: AppColors.muted,
                ),
              ),
              const SizedBox(height: 14),
              ActionButton(
                label: '見守る一覧に戻る',
                onPressed: () => Navigator.maybePop(context),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
