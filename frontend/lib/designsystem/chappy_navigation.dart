import 'package:flutter/material.dart';
import '../foundation/app_colors.dart';

class ChappyNavigation extends StatelessWidget {
  const ChappyNavigation({super.key, required this.onSelected});
  final ValueChanged<int> onSelected;
  static const labels = ['いま', '旅', '見守る', '手紙'];
  static const symbols = ['●', '⌁', '♡', '✉'];
  @override
  Widget build(BuildContext context) => Material(
    color: AppColors.surface,
    borderRadius: BorderRadius.circular(22),
    clipBehavior: Clip.antiAlias,
    child: Padding(
      padding: const EdgeInsets.all(8),
      child: Row(
        children: [
          for (var i = 0; i < labels.length; i++)
            Expanded(
              child: Semantics(
                selected: i == 0,
                child: InkWell(
                  onTap: () => onSelected(i),
                  borderRadius: BorderRadius.circular(16),
                  child: Container(
                    constraints: const BoxConstraints(minHeight: 48),
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    decoration: BoxDecoration(
                      color: i == 0 ? AppColors.soft : null,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        ExcludeSemantics(
                          child: Text(
                            symbols[i],
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.bold,
                              color: i == 0
                                  ? AppColors.primary
                                  : AppColors.muted,
                            ),
                          ),
                        ),
                        Text(
                          labels[i],
                          style: TextStyle(
                            fontSize: 10,
                            color: i == 0 ? AppColors.primary : AppColors.muted,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    ),
  );
}
