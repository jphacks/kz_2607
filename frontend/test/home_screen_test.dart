import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/main.dart';
import 'package:kz_2607/home_screen.dart';
import 'package:kz_2607/designsystem/journey_gauge.dart';

Future<void> loadHomeFont() async {
  for (final entry in {
    'NotoSansJP': ['NotoSansJP-Regular.ttf', 'NotoSansJP-Bold.ttf'],
    'NotoSans': ['NotoSans-Regular.ttf'],
    'NotoSansSymbols': ['NotoSansSymbols-Regular.ttf'],
    'NotoSansSymbols2': ['NotoSansSymbols2-Regular.ttf'],
  }.entries) {
    final loader = FontLoader(entry.key);
    for (final file in entry.value) {
      loader.addFont(rootBundle.load('assets/fonts/$file'));
    }
    await loader.load();
  }
}

void main() {
  setUpAll(loadHomeFont);
  testWidgets('home displays sample pet and honest disconnected status', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    await tester.pumpAndSettle();
    expect(find.text('いま、一緒にいる子'), findsOneWidget);
    expect(find.text('ポポ'), findsOneWidget);
    expect(find.text('旅立ちゲージ 72%'), findsOneWidget);
    await tester.ensureVisible(find.text('未接続 · M5Stackにつなぐ'));
    expect(find.text('接続済み · M5Stack / 設定'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets('navigation opens and closes the corresponding information', (
    tester,
  ) async {
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    for (final entry in {
      '見守る': '旅立ったペットの見守り画面は準備中です。',
      '手紙': '届いた手紙を読む画面は準備中です。',
    }.entries) {
      await tester.tap(find.text(entry.key));
      await tester.pumpAndSettle();
      expect(find.text(entry.value), findsOneWidget);
      await tester.tap(find.text('閉じる'));
      await tester.pumpAndSettle();
      expect(find.text(entry.value), findsNothing);
    }
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'narrow screen with large text remains scrollable without overflow',
    (tester) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pumpWidget(const MyApp(home: HomeScreen()));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('確定した交換結果を見る'),
        180,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.ensureVisible(find.text('確定した交換結果を見る'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('確定した交換結果を見る'));
      await tester.pumpAndSettle();
      expect(find.text('交換結果の表示は準備中です。'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('full journey gauge displays waiting state', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: Scaffold(body: JourneyGauge(value: 1))),
    );
    expect(find.text('旅立ちゲージ 100%'), findsOneWidget);
    expect(find.text('旅立ちの準備ができました。相手も100%になると自動交換。'), findsOneWidget);
  });
}
