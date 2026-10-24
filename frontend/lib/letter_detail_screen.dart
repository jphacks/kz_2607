import 'package:flutter/material.dart';
import 'designsystem/app_card.dart';
import 'designsystem/letter_preview_card.dart';
import 'foundation/app_colors.dart';
import 'foundation/models/pet_letter.dart';

class LetterDetailScreen extends StatelessWidget {
  const LetterDetailScreen({super.key, required this.letter});
  final PetLetter letter;
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('届いた手紙'),
      backgroundColor: AppColors.background,
      surfaceTintColor: Colors.transparent,
    ),
    body: SafeArea(
      child: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 12, 24, 32),
            child: AppCard(
              padding: 24,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.mark_email_read_outlined,
                    color: AppColors.primary,
                    size: 32,
                  ),
                  const SizedBox(height: 20),
                  Text(
                    '${letter.senderName}からの手紙',
                    style: const TextStyle(
                      fontSize: 22,
                      height: 1.5,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '${letterDate(letter.createdAt)} · 第${letter.generation}世代',
                    style: const TextStyle(
                      fontSize: 12,
                      height: 1.5,
                      color: AppColors.muted,
                    ),
                  ),
                  const SizedBox(height: 24),
                  const Divider(color: AppColors.soft),
                  const SizedBox(height: 20),
                  SelectableText(
                    letter.title,
                    style: const TextStyle(
                      fontSize: 16,
                      height: 1.6,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 16),
                  SelectableText(
                    letter.body,
                    style: const TextStyle(fontSize: 14, height: 2),
                  ),
                  const SizedBox(height: 24),
                  Align(
                    alignment: Alignment.centerRight,
                    child: Text(
                      '— ${letter.senderName}',
                      style: const TextStyle(
                        fontSize: 14,
                        color: AppColors.primary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
}
