import 'package:flutter/material.dart';
import '../foundation/app_colors.dart';
import 'app_card.dart';

class ConnectionMessageCard extends StatelessWidget {
  const ConnectionMessageCard({
    super.key,
    required this.title,
    required this.child,
    this.color = AppColors.surface,
  });
  final String title;
  final Widget child;
  final Color color;
  @override
  Widget build(BuildContext context) => AppCard(
    color: color,
    padding: 16,
    radius: 20,
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
        DefaultTextStyle.merge(
          style: const TextStyle(fontSize: 14, height: 1.5),
          child: child,
        ),
      ],
    ),
  );
}
