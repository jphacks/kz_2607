import 'package:flutter/material.dart';
import 'designsystem/app_card.dart';
import 'designsystem/bottom_navigation.dart';
import 'designsystem/first_pet_journey.dart';
import 'designsystem/pet_portrait.dart';
import 'designsystem/watch_information_card.dart';
import 'foundation/app_colors.dart';
import 'foundation/watch_pet.dart';
import 'letters_screen.dart';

class WatchScreen extends StatelessWidget {
  const WatchScreen({super.key, this.firstPet = WatchPet.firstCreatedSample});
  final WatchPet? firstPet;

  Widget _profile(BuildContext context) {
    final pet = firstPet!;
    final information = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          pet.name,
          style: const TextStyle(
            fontSize: 28,
            height: 1.4,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: AppColors.soft,
            borderRadius: BorderRadius.circular(999),
          ),
          child: const Text(
            '最初に生まれた子',
            style: TextStyle(
              fontSize: 11,
              height: 1.5,
              color: AppColors.primary,
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
        const SizedBox(height: 12),
        Text(
          pet.summary.replaceAll(' / ', '\n'),
          style: const TextStyle(
            fontSize: 13,
            height: 1.7,
            color: AppColors.muted,
          ),
        ),
      ],
    );
    final portrait = PetPortrait(name: pet.name, size: 136);
    return AppCard(
      padding: 20,
      radius: 24,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              if (constraints.maxWidth < 290 ||
                  MediaQuery.textScalerOf(context).scale(1) > 1.3) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Center(child: portrait),
                    const SizedBox(height: 18),
                    information,
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  portrait,
                  const SizedBox(width: 18),
                  Expanded(child: information),
                ],
              );
            },
          ),
          const SizedBox(height: 18),
          const Divider(height: 1, color: AppColors.background),
          const SizedBox(height: 14),
          const Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.favorite_border_rounded,
                size: 16,
                color: AppColors.primary,
              ),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'あなたからはじまった、大切な旅。',
                  style: TextStyle(
                    fontSize: 12,
                    height: 1.5,
                    color: AppColors.primary,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Column(
            children: [
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.all(24),
                  children: [
                    const Text(
                      '最初の子を見守る',
                      style: TextStyle(
                        fontSize: 24,
                        height: 1.5,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      '離れていても、この子の旅はつづいていく。',
                      style: TextStyle(
                        fontSize: 14,
                        height: 1.5,
                        color: AppColors.muted,
                      ),
                    ),
                    const SizedBox(height: 20),
                    if (firstPet == null)
                      const WatchInformationCard(
                        title: 'まだ最初の子の情報がありません',
                        body: '最初に作った子の情報を確認できると、ここから見守れます。',
                      )
                    else ...[
                      _profile(context),
                      const SizedBox(height: 28),
                      FirstPetJourney(firstPet: firstPet),
                    ],
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 18),
                child: BottomNavigation(
                  selectedIndex: 1,
                  onSelected: (index) {
                    if (index == 1) return;
                    if (index == 0) {
                      Navigator.maybePop(context);
                      return;
                    }
                    Navigator.of(context).pushReplacement<void, void>(
                      MaterialPageRoute(builder: (_) => const LettersScreen()),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
