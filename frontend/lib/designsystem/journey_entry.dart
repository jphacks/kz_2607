import 'package:flutter/material.dart';
import '../foundation/app_colors.dart';

class JourneyEntry extends StatelessWidget {
  const JourneyEntry({
    super.key,
    required this.ownerNumber,
    required this.title,
    required this.memory,
    this.isCurrent = false,
  });
  final int ownerNumber;
  final String title, memory;
  final bool isCurrent;

  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Container(
        constraints: const BoxConstraints(minWidth: 38, minHeight: 38),
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: isCurrent ? AppColors.primary : AppColors.petBackground,
        ),
        alignment: Alignment.center,
        child: Text(
          '$ownerNumber',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.bold,
            color: isCurrent ? Colors.white : AppColors.text,
          ),
        ),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 3),
            Text(
              memory,
              style: const TextStyle(fontSize: 11, color: AppColors.muted),
            ),
          ],
        ),
      ),
    ],
  );
}
