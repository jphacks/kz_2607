import 'package:flutter/material.dart';
import '../foundation/app_colors.dart';

class BottomNavigation extends StatelessWidget {
  const BottomNavigation({
    super.key,
    required this.onSelected,
    this.selectedIndex = 0,
  });
  final ValueChanged<int> onSelected;
  final int selectedIndex;
  static const labels = ['いま', '見守る', '手紙'];
  static const symbols = ['●', '♡', '✉'];
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
                selected: i == selectedIndex,
                child: InkWell(
                  onTap: () => onSelected(i),
                  borderRadius: BorderRadius.circular(16),
                  child: Container(
                    constraints: const BoxConstraints(minHeight: 48),
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    decoration: BoxDecoration(
                      color: i == selectedIndex ? AppColors.soft : null,
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
                              color: i == selectedIndex
                                  ? AppColors.primary
                                  : AppColors.muted,
                            ),
                          ),
                        ),
                        Text(
                          labels[i],
                          style: TextStyle(
                            fontSize: 10,
                            color: i == selectedIndex
                                ? AppColors.primary
                                : AppColors.muted,
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
