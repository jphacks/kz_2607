import 'package:flutter/material.dart';
import 'birth_screen.dart';
import 'core2_connection_screen.dart';
import 'exchange_result_screen.dart';
import 'letters_screen.dart';
import 'watch_screen.dart';
import 'designsystem/action_button.dart';
import 'designsystem/app_card.dart';
import 'designsystem/bottom_navigation.dart';
import 'designsystem/journey_gauge.dart';
import 'designsystem/current_pet_portrait.dart';
import 'foundation/app_colors.dart';
import 'foundation/app_spacing.dart';
import 'foundation/services/core2_ble.dart';
import 'foundation/controllers/home_pet_controller.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  final _pet = HomePetController();
  bool _wasBusy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  Core2Ble _ensureBle() {
    if (_ble == null) {
      _ble = Core2Ble();
      _ble!.voiceCloud.addListener(_syncPet);
    }
    return _ble!;
  }

  void _syncPet() {
    final cloud = _ble!.voiceCloud;
    final changed = _wasBusy && !cloud.busy;
    _wasBusy = cloud.busy;
    final rebound = _pet.bind(cloud.deviceId, cloud.petId);
    if (changed && !rebound) _pet.refresh();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _pet.refresh();
  }

  // Created on first use, retained when returning from the connection screen.
  Core2Ble? _ble;
  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _ble?.voiceCloud.removeListener(_syncPet);
    _pet.dispose();
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
    _ensureBle();
    setState(() {});
    await Navigator.of(context).push<void>(
      MaterialPageRoute(builder: (_) => Core2ConnectionPage(ble: _ble)),
    );
    if (mounted) {
      _syncPet();
      await _pet.refresh();
      if (mounted) setState(() {});
    }
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
    if (mounted) {
      _syncPet();
      await _pet.refresh();
      if (mounted) setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: Listenable.merge([_pet, if (_ble != null) _ble!]),
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
                      if (_pet.loading) const LinearProgressIndicator(),
                      if (_pet.pet == null)
                        AppCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _pet.error ??
                                    (_pet.loading
                                        ? 'ペット情報を読み込んでいます…'
                                        : 'M5に接続すると、この子の情報を表示します。'),
                                style: const TextStyle(height: 1.7),
                              ),
                              if (_pet.error != null)
                                TextButton(
                                  onPressed: _pet.loading ? null : _pet.refresh,
                                  child: const Text('もう一度読み込む'),
                                ),
                              if (_pet.diagnostic != null)
                                SelectableText(
                                  _pet.diagnostic!,
                                  style: const TextStyle(fontSize: 12),
                                ),
                            ],
                          ),
                        ),
                      if (_pet.pet != null) ...[
                        AppCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Center(
                                child: CurrentPetPortrait(
                                  name: _pet.pet!.name,
                                  appearance: _pet.pet!.appearance,
                                ),
                              ),
                              const SizedBox(height: 16),
                              Text(
                                _pet.pet!.name,
                                style: const TextStyle(
                                  fontSize: 25,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                'あなたは ${_pet.pet!.generation}人目',
                                style: const TextStyle(
                                  color: AppColors.primary,
                                ),
                              ),
                              if (_pet.pet!.createdAt != null)
                                Text(
                                  '旅の日数 ${DateTime.now().difference(_pet.pet!.createdAt!).inDays.clamp(0, 999999) + 1}日',
                                  style: const TextStyle(
                                    color: AppColors.muted,
                                    height: 1.7,
                                  ),
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
                        AppCard(
                          color: AppColors.soft,
                          padding: 14,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _pet.pet!.description,
                                style: const TextStyle(
                                  color: AppColors.primary,
                                  fontWeight: FontWeight.bold,
                                  height: 1.7,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                '一人称：${_pet.pet!.firstPerson}',
                                style: const TextStyle(fontSize: 12),
                              ),
                              Text(
                                '話し方：${_pet.pet!.speechNote}',
                                style: const TextStyle(
                                  fontSize: 12,
                                  height: 1.7,
                                ),
                              ),
                              if (_pet.pet!.learnedWords.isNotEmpty)
                                Text(
                                  '覚えた言葉：${_pet.pet!.learnedWords.join("・")}',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    height: 1.7,
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ],
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
                      if (_pet.pet != null)
                        JourneyGauge(value: _pet.pet!.gauge)
                      else
                        const AppCard(
                          child: Text(
                            '旅立ちゲージはペット情報を取得すると表示されます。',
                            style: TextStyle(height: 1.7),
                          ),
                        ),
                      const SizedBox(height: 12),
                      ActionButton(
                        label: _ble?.ready == true
                            ? '接続済み · M5Stack / 設定'
                            : '未接続 · M5Stackにつなぐ',
                        onPressed: _openConnection,
                      ),
                      if (_pet.pet != null && !_pet.pet!.born) ...[
                        const SizedBox(height: 12),
                        ActionButton(
                          label: 'キャラクターを誕生させる・続きから',
                          onPressed: _openBirth,
                        ),
                      ],
                      const SizedBox(height: 12),
                      ActionButton(
                        label: '確定した交換結果を見る',
                        onPressed: () {
                          _ble ??= Core2Ble();
                          setState(() {});
                          Navigator.of(context).push<void>(
                            MaterialPageRoute(
                              builder: (_) => ExchangeResultScreen(ble: _ble!),
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 12),
                      TextButton(
                        onPressed: _pet.loading ? null : _pet.refresh,
                        child: const Text('ペット情報を更新'),
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
                            builder: (_) => const WatchScreen(),
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
