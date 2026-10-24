import 'package:flutter/material.dart';
import '../foundation/app_colors.dart';
import 'chappy_card.dart';

class JourneyGauge extends StatelessWidget {
  const JourneyGauge({super.key, required this.value});
  final double value;
  @override
  Widget build(BuildContext context) {
    final normalized = value.clamp(0.0, 1.0);
    final percent = (normalized * 100).round();
    return ChappyCard(
      color: AppColors.soft,
      padding: 16,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '旅立ちゲージ $percent%',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          Text(
            normalized == 1
                ? '旅立ちの準備ができました。相手も100%になると自動交換。'
                : '双方が100%になると、すれ違いで自動交換。',
            style: const TextStyle(fontSize: 14),
          ),
          const SizedBox(height: 8),
          LinearProgressIndicator(
            value: normalized,
            minHeight: 10,
            borderRadius: BorderRadius.circular(5),
            color: AppColors.primary,
            backgroundColor: AppColors.gaugeTrack,
            semanticsLabel: '旅立ちゲージ',
            semanticsValue: '$percent%',
          ),
        ],
      ),
    );
  }
}
