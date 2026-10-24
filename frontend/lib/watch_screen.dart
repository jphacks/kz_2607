import 'package:flutter/material.dart';
import 'designsystem/action_button.dart';
import 'designsystem/bottom_navigation.dart';
import 'designsystem/watch_information_card.dart';
import 'foundation/app_colors.dart';
import 'foundation/watch_pet.dart';
import 'journey_screen.dart';
import 'watch_pet_screen.dart';

class WatchScreen extends StatelessWidget {
  const WatchScreen({super.key, this.pets = WatchPet.samples});
  final List<WatchPet> pets;

  void _letters(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '手紙',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 16),
              const Text('届いた手紙を読む画面は準備中です。'),
              const SizedBox(height: 24),
              ActionButton(
                label: '閉じる',
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
        ),
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
                      '見守る',
                      style: TextStyle(
                        fontSize: 11,
                        height: 1.5,
                        color: AppColors.muted,
                      ),
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      '旅先のペットたち',
                      style: TextStyle(
                        fontSize: 24,
                        height: 1.5,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      '送り出したペットを見守る',
                      style: TextStyle(
                        fontSize: 14,
                        height: 1.5,
                        color: AppColors.muted,
                      ),
                    ),
                    const SizedBox(height: 14),
                    if (pets.isEmpty) ...[
                      const WatchInformationCard(
                        title: 'まだ旅立ったペットはいません',
                        body: '交換で旅立つと、その後の旅をここから見守れます。',
                      ),
                    ] else ...[
                      for (var index = 0; index < pets.length; index++) ...[
                        WatchInformationCard(
                          title: pets[index].name,
                          body: pets[index].summary,
                          highlighted: index == 0,
                        ),
                        const SizedBox(height: 14),
                        ActionButton(
                          label: '${pets[index].name}のようすを見る',
                          onPressed: () => Navigator.of(context).push<void>(
                            MaterialPageRoute(
                              builder: (_) => WatchPetScreen(pet: pets[index]),
                            ),
                          ),
                        ),
                        const SizedBox(height: 14),
                      ],
                      const Text(
                        '名前・日時・旅の記録は表示サンプルです。',
                        style: TextStyle(
                          fontSize: 12,
                          height: 1.5,
                          color: AppColors.muted,
                        ),
                      ),
                      const SizedBox(height: 14),
                      ActionButton(
                        label: '届いた手紙を見る',
                        onPressed: () => _letters(context),
                      ),
                    ],
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 18),
                child: BottomNavigation(
                  selectedIndex: 2,
                  onSelected: (index) {
                    if (index == 2) return;
                    if (index == 0) {
                      Navigator.maybePop(context);
                      return;
                    }
                    if (index == 1) {
                      Navigator.of(context).pushReplacement<void, void>(
                        MaterialPageRoute(
                          builder: (_) => const JourneyScreen(),
                        ),
                      );
                      return;
                    }
                    _letters(context);
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
