import 'package:flutter/material.dart';
import 'app_card.dart';
import '../foundation/app_colors.dart';

class WatchInformationCard extends StatelessWidget {
  const WatchInformationCard({
    super.key,
    required this.title,
    required this.body,
    this.highlighted = false,
  });
  final String title, body;
  final bool highlighted;
  @override
  Widget build(BuildContext context) => AppCard(
    padding: 16,
    radius: 20,
    color: highlighted ? AppColors.soft : AppColors.surface,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            fontSize: 16,
            height: 1.5,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 8),
        Text(body, style: const TextStyle(fontSize: 14, height: 1.5)),
      ],
    ),
  );
}
