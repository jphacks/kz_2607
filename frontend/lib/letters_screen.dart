import 'package:flutter/material.dart';
import 'designsystem/action_button.dart';
import 'designsystem/app_card.dart';
import 'designsystem/bottom_navigation.dart';
import 'designsystem/letter_preview_card.dart';
import 'foundation/app_colors.dart';
import 'foundation/controllers/letters_controller.dart';
import 'letter_detail_screen.dart';
import 'watch_screen.dart';

class LettersScreen extends StatefulWidget {
  const LettersScreen({super.key, this.controller});
  final LettersController? controller;
  @override
  State<LettersScreen> createState() => _LettersScreenState();
}

class _LettersScreenState extends State<LettersScreen> {
  late final _controller = widget.controller ?? LettersController();
  @override
  void initState() {
    super.initState();
    _controller.load();
  }

  @override
  void dispose() {
    if (widget.controller == null) _controller.dispose();
    super.dispose();
  }

  Widget _notice(IconData icon, String title, String body) => AppCard(
    padding: 24,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.all(14),
          decoration: const BoxDecoration(
            color: AppColors.soft,
            shape: BoxShape.circle,
          ),
          child: Icon(icon, color: AppColors.primary, size: 28),
        ),
        const SizedBox(height: 20),
        Text(
          title,
          style: const TextStyle(
            fontSize: 18,
            height: 1.5,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 10),
        Text(
          body,
          style: const TextStyle(
            fontSize: 14,
            height: 1.8,
            color: AppColors.muted,
          ),
        ),
      ],
    ),
  );

  List<Widget> _content() {
    if (_controller.loading) {
      return [
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 48),
          child: Center(child: CircularProgressIndicator()),
        ),
        const Center(
          child: Text('手紙を受け取っています…', style: TextStyle(color: AppColors.muted)),
        ),
      ];
    }
    if (_controller.error != null) {
      return [
        _notice(Icons.cloud_off_rounded, '手紙を取得できませんでした', _controller.error!),
        const SizedBox(height: 16),
        ActionButton(label: 'もう一度読み込む', onPressed: _controller.load),
        if (_controller.diagnostic != null)
          ExpansionTile(
            title: const Text('エラーの詳細'),
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: SelectableText(_controller.diagnostic!),
              ),
            ],
          ),
      ];
    }
    if (_controller.letters.isEmpty) {
      return [
        _notice(
          Icons.mail_outline_rounded,
          'まだ手紙は届いていません',
          '最初に作った子が旅立つと、旅の近況が手紙で届きます。\n次の便りを、ゆっくり待ちましょう。',
        ),
      ];
    }
    return [
      Text(
        '${_controller.letters.length}通の旅の便り',
        style: const TextStyle(fontSize: 12, color: AppColors.muted),
      ),
      const SizedBox(height: 14),
      for (final letter in _controller.letters) ...[
        LetterPreviewCard(
          letter: letter,
          onTap: () => Navigator.of(context).push<void>(
            MaterialPageRoute(
              builder: (_) => LetterDetailScreen(letter: letter),
            ),
          ),
        ),
        const SizedBox(height: 16),
      ],
    ];
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _controller,
    builder: (context, _) => Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: Column(
              children: [
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: _controller.load,
                    child: ListView(
                      padding: const EdgeInsets.fromLTRB(24, 28, 24, 24),
                      physics: const AlwaysScrollableScrollPhysics(),
                      children: [
                        Row(
                          children: [
                            const Expanded(
                              child: Text(
                                '手紙',
                                style: TextStyle(
                                  fontSize: 24,
                                  height: 1.5,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                            IconButton(
                              tooltip: '手紙を更新',
                              onPressed: _controller.loading
                                  ? null
                                  : _controller.load,
                              icon: const Icon(
                                Icons.refresh_rounded,
                                color: AppColors.primary,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        const Text(
                          '離れていても、言葉は届く。',
                          style: TextStyle(
                            fontSize: 14,
                            height: 1.6,
                            color: AppColors.muted,
                          ),
                        ),
                        const SizedBox(height: 24),
                        ..._content(),
                        const SizedBox(height: 20),
                        const Text(
                          'あなたが最初に作った子からの、一方通行の手紙。\n返信せずに、旅のつづきを見守れます。',
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
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 0, 24, 18),
                  child: BottomNavigation(
                    selectedIndex: BottomNavigation.labels.indexOf('手紙'),
                    onSelected: (index) {
                      final label = BottomNavigation.labels[index];
                      if (label == '手紙') return;
                      if (label == 'いま') {
                        Navigator.maybePop(context);
                        return;
                      }
                      if (label == '見守る') {
                        Navigator.of(context).pushReplacement<void, void>(
                          MaterialPageRoute(
                            builder: (_) => const WatchScreen(),
                          ),
                        );
                        return;
                      }
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
