import 'package:flutter/material.dart';
import 'designsystem/app_card.dart';
import 'designsystem/action_button.dart';
import 'designsystem/bottom_navigation.dart';
import 'designsystem/journey_entry.dart';
import 'foundation/app_colors.dart';
import 'foundation/app_spacing.dart';
import 'watch_screen.dart';

/// Sample content from the approved Figma. Server data will replace it later.
class JourneyScreen extends StatelessWidget {
  const JourneyScreen({super.key});

  void _showInfo(BuildContext context, int index) {
    const message = '届いた手紙を読む画面は準備中です。';
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
              Text(
                BottomNavigation.labels[index],
                style: const TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 16),
              Text(message),
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
    backgroundColor: AppColors.background,
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Column(
            children: [
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(24, 28, 24, 16),
                  children: [
                    const Text(
                      'ポポの旅',
                      style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.medium),
                    const Text(
                      '旅の履歴・受け継いだもの（表示サンプル）',
                      style: TextStyle(fontSize: 13, color: AppColors.muted),
                    ),
                    const SizedBox(height: AppSpacing.medium),
                    const AppCard(
                      child: Column(
                        children: [
                          JourneyEntry(
                            ownerNumber: 1,
                            title: '最初の家 ・ 好奇心の芽',
                            memory: '新しいことへの好奇心が育った',
                          ),
                          SizedBox(height: 14),
                          JourneyEntry(
                            ownerNumber: 2,
                            title: '次の家 ・ 冒険好きに',
                            memory: '毎日たくさん一緒に歩いた',
                          ),
                          SizedBox(height: 14),
                          JourneyEntry(
                            ownerNumber: 3,
                            title: '前の家 ・ 「ありがとう」',
                            memory: 'よく褒めてもらった',
                          ),
                          SizedBox(height: 14),
                          JourneyEntry(
                            ownerNumber: 5,
                            title: 'いま ・ あなたと一緒',
                            memory: '新しい記憶を育てている',
                            isCurrent: true,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: AppSpacing.medium),
                    const AppCard(
                      color: AppColors.memoryBackground,
                      padding: 14,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'AIがつないだ思い出',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.bold,
                              color: AppColors.primary,
                            ),
                          ),
                          SizedBox(height: 6),
                          Text(
                            '「昔、毎日いろんな道を歩いたんだ。そのころから知らない場所が好きになったよ。」',
                            style: TextStyle(fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: AppSpacing.medium),
                    const Text(
                      '飼い主は匿名で表示。公開可能な成長記録を使い、個人的な会話は履歴に出しません。',
                      style: TextStyle(
                        fontSize: 12,
                        color: AppColors.muted,
                        height: 1.5,
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 18),
                child: BottomNavigation(
                  selectedIndex: 1,
                  onSelected: (index) {
                    if (index == 1) return;
                    if (index == 2) {
                      Navigator.of(context).pushReplacement<void, void>(
                        MaterialPageRoute(builder: (_) => const WatchScreen()),
                      );
                      return;
                    }
                    if (index == 0) {
                      Navigator.pop(context);
                      return;
                    }
                    _showInfo(context, index);
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
