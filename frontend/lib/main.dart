import 'package:flutter/material.dart';
import 'home_screen.dart';
import 'foundation/app_colors.dart';

void main() => runApp(const ChappyApp());

class ChappyApp extends StatelessWidget {
  const ChappyApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'チャッピー',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: 'NotoSansJP',
      fontFamilyFallback: const ['NotoSans', 'NotoSansSymbols2'],
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        primary: AppColors.primary,
        surface: AppColors.surface,
      ),
      textTheme:
          ThemeData(
            fontFamily: 'NotoSansJP',
            fontFamilyFallback: const ['NotoSans', 'NotoSansSymbols2'],
          ).textTheme.apply(
            bodyColor: AppColors.text,
            displayColor: AppColors.text,
          ),
    ),
    home: const HomeScreen(),
  );
}
