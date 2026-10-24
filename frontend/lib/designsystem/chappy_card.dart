import 'package:flutter/material.dart';
import '../foundation/app_colors.dart';
import '../foundation/app_spacing.dart';

class ChappyCard extends StatelessWidget {
  const ChappyCard({
    super.key,
    required this.child,
    this.color = AppColors.surface,
    this.padding = AppSpacing.card,
  });
  final Widget child;
  final Color color;
  final double padding;
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: EdgeInsets.all(padding),
    decoration: BoxDecoration(
      color: color,
      borderRadius: BorderRadius.circular(24),
    ),
    child: child,
  );
}
