import 'package:flutter/material.dart';
import 'designsystem/app_card.dart';
import 'foundation/app_colors.dart';
import 'foundation/models/exchange_record.dart';
import 'foundation/services/core2_ble.dart';

/// Shares the Home-owned connection. Opening the screen only displays records.
class ExchangeResultScreen extends StatelessWidget {
  const ExchangeResultScreen({super.key, required this.ble});
  final Core2Ble ble;

  Widget _record(ExchangeRecord record) {
    final exchange = record.exchange;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: AppCard(
        padding: 24,
        radius: 24,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              record.cancelled
                  ? Icons.undo_rounded
                  : record.completed
                  ? Icons.swap_horiz_rounded
                  : Icons.hourglass_top_rounded,
              color: AppColors.primary,
              size: 32,
            ),
            const SizedBox(height: 12),
            Text(
              record.status,
              style: const TextStyle(
                fontSize: 20,
                height: 1.5,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              record.acknowledged
                  ? 'M5で結果を受け取ったことを確認しました。'
                  : record.completed || record.cancelled
                  ? 'サーバーの結果は確定しています。M5での受信はまだ確認できていません。'
                  : 'まだ交換は確定していません。確認が終わるまでお待ちください。',
              style: const TextStyle(color: AppColors.muted, height: 1.7),
            ),
            const SizedBox(height: 20),
            Text(
              record.completed && record.acknowledged ? '旅立った子' : '手放す候補の子',
              style: const TextStyle(color: AppColors.muted),
            ),
            const SizedBox(height: 6),
            SelectableText(
              exchange.givenPetId,
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Icon(Icons.swap_vert_rounded, color: AppColors.primary),
            ),
            Text(
              record.completed && record.acknowledged ? '迎えた子' : '受け取る候補の子',
              style: const TextStyle(color: AppColors.muted),
            ),
            const SizedBox(height: 6),
            SelectableText(
              exchange.gotPetId,
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            if (record.cancelled) ...[
              const SizedBox(height: 16),
              const Text(
                '交換は成立していません。元の子と過ごします。',
                style: TextStyle(height: 1.7),
              ),
            ],
            const SizedBox(height: 16),
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              title: const Text('交換の詳細'),
              children: [
                Align(
                  alignment: Alignment.centerLeft,
                  child: SelectableText(
                    '交換ID: ${exchange.transactionId}\n自分の端末: ${exchange.myDeviceId}\n相手の端末: ${exchange.peerDeviceId}\n候補の距離: ${exchange.distanceMeters.toStringAsFixed(3)} m',
                    style: const TextStyle(fontSize: 12, height: 1.8),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: ble,
    builder: (context, _) => AnimatedBuilder(
      animation: ble.exchange ?? const AlwaysStoppedAnimation<double>(0),
      builder: (context, _) {
        final controller = ble.exchange;
        final records = controller?.records ?? const <ExchangeRecord>[];
        return Scaffold(
          backgroundColor: AppColors.background,
          appBar: AppBar(
            title: const Text('交換結果'),
            backgroundColor: AppColors.background,
            surfaceTintColor: Colors.transparent,
          ),
          body: SafeArea(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 480),
                child: ListView(
                  padding: const EdgeInsets.all(24),
                  children: [
                    const Text(
                      '出会いのあとを、ここで確認。',
                      style: TextStyle(
                        fontSize: 22,
                        height: 1.5,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      'このアプリに保存した交換を、候補を受け取った順の新しいものから表示します。',
                      style: TextStyle(color: AppColors.muted, height: 1.7),
                    ),
                    const SizedBox(height: 24),
                    if (controller?.restoring == true ||
                        controller?.busy == true) ...[
                      const LinearProgressIndicator(),
                      const SizedBox(height: 16),
                    ],
                    if (controller == null)
                      const AppCard(
                        padding: 24,
                        radius: 24,
                        child: Text(
                          'M5に接続すると、保存済みの交換結果を確認できます。',
                          style: TextStyle(height: 1.7),
                        ),
                      ),
                    if (controller != null &&
                        records.isEmpty &&
                        !controller.restoring)
                      const AppCard(
                        padding: 24,
                        radius: 24,
                        child: Column(
                          children: [
                            Icon(
                              Icons.swap_horiz_rounded,
                              size: 40,
                              color: AppColors.primary,
                            ),
                            SizedBox(height: 16),
                            Text(
                              '交換の記録はまだありません',
                              style: TextStyle(
                                fontWeight: FontWeight.bold,
                                fontSize: 18,
                              ),
                            ),
                            SizedBox(height: 12),
                            Text(
                              'M5から交換候補を受信すると、ここに結果が表示されます。',
                              style: TextStyle(
                                color: AppColors.muted,
                                height: 1.7,
                              ),
                            ),
                          ],
                        ),
                      ),
                    for (final record in records) _record(record),
                    const SizedBox(height: 16),
                    Text(
                      ble.exchangeStatus,
                      style: const TextStyle(
                        color: AppColors.muted,
                        height: 1.7,
                      ),
                    ),
                    if (controller?.hasUnresolved == true) ...[
                      const SizedBox(height: 16),
                      FilledButton(
                        onPressed:
                            ble.ready &&
                                controller?.busy == false &&
                                controller?.candidate != null
                            ? ble.processExchange
                            : null,
                        child: const Text('交換結果を再確認'),
                      ),
                      if (!ble.ready)
                        const Text(
                          '再確認するには、交換したM5に接続してください。',
                          style: TextStyle(color: AppColors.muted, height: 1.7),
                        ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        );
      },
    ),
  );
}
