import 'package:flutter/material.dart';
import 'login_screen.dart';
import 'foundation/app_colors.dart';

void main() => runApp(const MyApp());

class MyApp extends StatelessWidget {
  const MyApp({super.key, this.home});
  final Widget? home;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'kz_2607',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: 'NotoSansJP',
      fontFamilyFallback: const [
        'NotoSans',
        'NotoSansSymbols',
        'NotoSansSymbols2',
      ],
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        primary: AppColors.primary,
        surface: AppColors.surface,
      ),
      textTheme:
          ThemeData(
            fontFamily: 'NotoSansJP',
            fontFamilyFallback: const [
              'NotoSans',
              'NotoSansSymbols',
              'NotoSansSymbols2',
            ],
          ).textTheme.apply(
            bodyColor: AppColors.text,
            displayColor: AppColors.text,
          ),
    ),
    home: home ?? const LoginScreen(),
  );
}
