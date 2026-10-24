import 'package:flutter/material.dart';
import 'birth_screen.dart';
import 'core2_connection_screen.dart';
import 'letters_screen.dart';
import 'watch_screen.dart';
import 'foundation/watch_pet.dart';
import 'designsystem/action_button.dart';
import 'designsystem/app_card.dart';
import 'designsystem/bottom_navigation.dart';
import 'designsystem/journey_gauge.dart';
import 'foundation/app_colors.dart';
import 'foundation/app_spacing.dart';
import 'foundation/services/core2_ble.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, this.firstPet = WatchPet.firstCreatedSample});
  final WatchPet? firstPet;
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  // Created on first use, retained when returning from the connection screen.
  Core2Ble? _ble;
  @override
  void dispose() {
    _ble?.dispose();
    super.dispose();
  }

  void _showInfo(String title, String message) {
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
                title,
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

  Future<void> _openConnection() async {
    _ble ??= Core2Ble();
    setState(() {});
    await Navigator.of(context).push<void>(
      MaterialPageRoute(builder: (_) => Core2ConnectionPage(ble: _ble)),
    );
    if (mounted) setState(() {});
  }

  Future<void> _openBirth() async {
    if (_ble?.ready != true || _ble?.voiceCloud.petId == null) {
      await _openConnection();
    }
    if (!mounted) return;
    final cloud = _ble?.voiceCloud;
    final deviceId = cloud?.deviceId;
    final petId = cloud?.petId;
    if (_ble?.ready != true || deviceId == null || petId == null) {
      _showInfo(
        'M5を先に登録してください',
        'M5Stackを接続し、端末登録が完了してから「キャラクターを誕生させる」を押してください。',
      );
      return;
    }
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => BirthScreen(
          deviceId: deviceId,
          petId: petId,
          canContinue: () =>
              _ble?.ready == true &&
              _ble?.voiceCloud.deviceId == deviceId &&
              _ble?.voiceCloud.petId == petId,
        ),
      ),
    );
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _ble ?? const AlwaysStoppedAnimation<double>(0),
    builder: (context, _) => Scaffold(
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
                        'いま、一緒にいる子',
                        style: TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.medium),
                      AppCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            LayoutBuilder(
                              builder: (context, constraints) {
                                final compact =
                                    constraints.maxWidth < 280 ||
                                    MediaQuery.textScalerOf(context).scale(1) >
                                        1.3;
                                final portrait = Container(
                                  width: 130,
                                  height: 130,
                                  decoration: const BoxDecoration(
                                    color: AppColors.petBackground,
                                    shape: BoxShape.circle,
                                  ),
                                  alignment: Alignment.topLeft,
                                  padding: const EdgeInsets.only(
                                    left: 15,
                                    top: 26,
                                  ),
                                  child: const Text(
                                    '●ᴥ●',
                                    semanticsLabel: 'ペットの表示サンプル',
                                    style: TextStyle(fontSize: 30),
                                  ),
                                );
                                final info = Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    const Text(
                                      'ポポ',
                                      style: TextStyle(
                                        fontSize: 25,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                    const SizedBox(height: 7),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 10,
                                        vertical: 6,
                                      ),
                                      decoration: BoxDecoration(
                                        color: AppColors.soft,
                                        borderRadius: BorderRadius.circular(
                                          999,
                                        ),
                                      ),
                                      child: const Text(
                                        'あなたは 5人目',
                                        style: TextStyle(
                                          fontSize: 11,
                                          color: AppColors.primary,
                                          fontWeight: FontWeight.bold,
                                        ),
                                      ),
                                    ),
                                    const SizedBox(height: 7),
                                    const Text(
                                      '旅の日数 27日',
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: AppColors.muted,
                                      ),
                                    ),
                                  ],
                                );
                                return compact
                                    ? Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          portrait,
                                          const SizedBox(height: 16),
                                          info,
                                        ],
                                      )
                                    : Row(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          portrait,
                                          const SizedBox(width: 16),
                                          Expanded(child: info),
                                        ],
                                      );
                              },
                            ),
                            const SizedBox(height: 12),
                            const Text(
                              '種族・性格は自動決定（表示サンプル）',
                              style: TextStyle(fontSize: 14),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'この子に残っているもの',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 16),
                      const AppCard(
                        color: AppColors.soft,
                        padding: 14,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '性格：好奇心旺盛（自動決定）',
                              style: TextStyle(
                                fontSize: 14,
                                color: AppColors.primary,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            SizedBox(height: 8),
                            Text(
                              '一人称：ぼく / 語尾：〜だよ（表示専用）',
                              style: TextStyle(fontSize: 12),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        '育成はガジェットで',
                        style: TextStyle(
                          fontSize: 13,
                          color: AppColors.muted,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        '話す・遊ぶ・一緒に歩くことで、この子にあなたの痕跡が残ります。',
                        style: TextStyle(fontSize: 12, color: AppColors.muted),
                      ),
                      const SizedBox(height: 16),
                      const JourneyGauge(value: 0.72),
                      const SizedBox(height: 12),
                      ActionButton(
                        label: _ble?.ready == true
                            ? '接続済み · M5Stack / 設定'
                            : '未接続 · M5Stackにつなぐ',
                        onPressed: _openConnection,
                      ),
                      const SizedBox(height: 12),
                      ActionButton(
                        label: 'キャラクターを誕生させる・続きから',
                        onPressed: _openBirth,
                      ),
                      const SizedBox(height: 12),
                      ActionButton(
                        label: '確定した交換結果を見る',
                        onPressed: () => _showInfo('交換結果', '交換結果の表示は準備中です。'),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'ペット情報・旅立ちゲージは表示サンプルです。',
                        style: TextStyle(fontSize: 11, color: AppColors.muted),
                      ),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 0, 24, 18),
                  child: BottomNavigation(
                    onSelected: (index) {
                      if (index == 0) return;
                      if (BottomNavigation.labels[index] == '手紙') {
                        Navigator.of(context).push<void>(
                          MaterialPageRoute(
                            builder: (_) => const LettersScreen(),
                          ),
                        );
                        return;
                      }
                      if (index == 1) {
                        Navigator.of(context).push<void>(
                          MaterialPageRoute(
                            builder: (_) =>
                                WatchScreen(firstPet: widget.firstPet),
                          ),
                        );
                        return;
                      }
                      _showInfo('手紙', '届いた手紙を読む画面は準備中です。');
                    },
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
