import 'package:flutter/material.dart';
import 'app_card.dart';
import 'watch_information_card.dart';
import '../foundation/app_colors.dart';
import '../foundation/watch_pet.dart';
import '../journey_detail_screen.dart';

class FirstPetJourney extends StatelessWidget {
  const FirstPetJourney({super.key, required this.firstPet});
  final WatchPet? firstPet;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const Text(
        '旅の履歴',
        style: TextStyle(
          fontSize: 18,
          height: 1.5,
          fontWeight: FontWeight.bold,
        ),
      ),
      const SizedBox(height: 6),
      const Text(
        'はじまりから、いまへ',
        style: TextStyle(fontSize: 12, height: 1.5, color: AppColors.muted),
      ),
      const SizedBox(height: 16),
      if (firstPet == null)
        const WatchInformationCard(
          title: 'まだ旅の記録がありません',
          body: '最初の子と出会うと、ここに旅の記録が残ります。',
        )
      else ...[
        AppCard(
          padding: 20,
          radius: 24,
          child: Column(
            children: [
              _JourneyStop(
                icon: Icons.home_outlined,
                label: 'はじまり',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => JourneyDetailScreen(
                      pet: firstPet!,
                      stage: JourneyStage.beginning,
                    ),
                  ),
                ),
                title: 'あなたとはじまった旅',
                body: firstPet!.sharedDays,
              ),
              _JourneyStop(
                icon: Icons.route_outlined,
                label: 'つながる思い出',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => JourneyDetailScreen(
                      pet: firstPet!,
                      stage: JourneyStage.memories,
                    ),
                  ),
                ),
                title: 'これまでの出会い',
                body: firstPet!.encounters,
              ),
              _JourneyStop(
                icon: Icons.explore_outlined,
                label: 'いま',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => JourneyDetailScreen(
                      pet: firstPet!,
                      stage: JourneyStage.present,
                    ),
                  ),
                ),
                title: '旅はつづいています',
                body: firstPet!.summary,
                current: true,
                last: true,
              ),
            ],
          ),
        ),
        const SizedBox(height: 18),
        const Text(
          '最初に作った子の旅を見守れます。手紙は「手紙」タブへ。',
          style: TextStyle(fontSize: 12, height: 1.6, color: AppColors.muted),
        ),
        const SizedBox(height: 8),
        const Text(
          'キャラクター・近況・履歴は表示サンプルです。飼い主は匿名で表示します。',
          style: TextStyle(fontSize: 11, height: 1.6, color: AppColors.muted),
        ),
      ],
    ],
  );
}

class _JourneyStop extends StatelessWidget {
  const _JourneyStop({
    required this.icon,
    required this.label,
    required this.title,
    required this.body,
    required this.onTap,
    this.current = false,
    this.last = false,
  });
  final VoidCallback onTap;
  final IconData icon;
  final String label, title, body;
  final bool current, last;
  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    borderRadius: BorderRadius.circular(12),
    child: IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 32,
            child: Column(
              children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: current ? AppColors.primary : AppColors.soft,
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    icon,
                    size: 16,
                    color: current ? Colors.white : AppColors.primary,
                  ),
                ),
                if (!last)
                  Expanded(
                    child: Container(
                      width: 2,
                      margin: const EdgeInsets.symmetric(vertical: 6),
                      color: AppColors.soft,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: last ? 0 : 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: const TextStyle(
                      fontSize: 11,
                      height: 1.5,
                      color: AppColors.primary,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    title,
                    style: const TextStyle(
                      fontSize: 14,
                      height: 1.5,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    body,
                    style: const TextStyle(
                      fontSize: 12,
                      height: 1.7,
                      color: AppColors.muted,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const Padding(
            padding: EdgeInsets.only(left: 8, top: 24),
            child: Icon(Icons.chevron_right_rounded, color: AppColors.primary),
          ),
        ],
      ),
    ),
  );
}
