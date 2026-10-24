import 'package:flutter/material.dart';
import 'app_card.dart';
import '../foundation/app_colors.dart';

class AuthenticationField extends StatelessWidget {
  const AuthenticationField({
    super.key,
    required this.label,
    required this.controller,
    this.password = false,
    this.enabled = true,
    this.onSubmitted,
  });
  final String label;
  final TextEditingController controller;
  final bool password, enabled;
  final VoidCallback? onSubmitted;

  @override
  Widget build(BuildContext context) => AppCard(
    padding: 16,
    radius: 20,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            fontSize: 12,
            height: 1.5,
            fontWeight: FontWeight.bold,
            color: AppColors.muted,
          ),
        ),
        const SizedBox(height: 8),
        TextFormField(
          controller: controller,
          enabled: enabled,
          obscureText: password,
          autocorrect: false,
          enableSuggestions: false,
          keyboardType: password
              ? TextInputType.visiblePassword
              : TextInputType.emailAddress,
          textInputAction: password
              ? TextInputAction.done
              : TextInputAction.next,
          autofillHints: [
            password ? AutofillHints.password : AutofillHints.email,
          ],
          style: const TextStyle(fontSize: 16, height: 1.5),
          decoration: InputDecoration(
            isDense: true,
            contentPadding: EdgeInsets.zero,
            border: InputBorder.none,
            enabledBorder: InputBorder.none,
            focusedBorder: InputBorder.none,
            disabledBorder: InputBorder.none,
            hintText: password ? '••••••••••••' : 'you@example.com',
            hintStyle: const TextStyle(color: AppColors.muted),
            errorMaxLines: 3,
          ),
          validator: (value) {
            if (value == null ||
                (password ? value.isEmpty : value.trim().isEmpty)) {
              return '$labelを入力してください。';
            }
            if (!password &&
                !RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$').hasMatch(value.trim())) {
              return 'メールアドレスの形式を確認してください。';
            }
            return null;
          },
          onFieldSubmitted: (_) {
            if (password) {
              onSubmitted?.call();
            } else {
              FocusScope.of(context).nextFocus();
            }
          },
        ),
      ],
    ),
  );
}
