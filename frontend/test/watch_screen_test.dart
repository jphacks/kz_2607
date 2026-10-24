import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/main.dart';
import 'package:kz_2607/home_screen.dart';
import 'package:kz_2607/journey_screen.dart';
import 'package:kz_2607/watch_screen.dart';
import 'package:kz_2607/watch_pet_screen.dart';
import 'home_screen_test.dart' show loadHomeFont;

void main() {
  setUpAll(loadHomeFont);
  Future<void> tap(WidgetTester tester, String text) async {
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text(text),
      100,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text(text));
    await tester.pumpAndSettle();
  }

  testWidgets('watch opens from home and shows only the selected pet journey', (
    tester,
  ) async {
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    await tap(tester, '見守る');
    expect(find.byType(WatchScreen), findsOneWidget);
    expect(find.text('旅先のペットたち'), findsOneWidget);
    await tap(tester, 'ミロのようすを見る');
    expect(find.text('ミロの旅'), findsOneWidget);
    expect(find.text('7人目の飼い主として一緒に暮らしました。'), findsOneWidget);
    await tap(tester, '見守る一覧に戻る');
    await tap(tester, 'ポポのようすを見る');
    expect(find.text('ポポの旅'), findsOneWidget);
    expect(find.text('7人目の飼い主として一緒に暮らしました。'), findsNothing);
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    await tap(tester, 'いま');
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.byType(WatchScreen), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets('journey and watch navigation preserves one home route', (
    tester,
  ) async {
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    await tap(tester, '旅');
    await tap(tester, '見守る');
    expect(find.byType(WatchScreen), findsOneWidget);
    await tap(tester, '旅');
    expect(find.byType(JourneyScreen), findsOneWidget);
    expect(find.byType(WatchScreen), findsNothing);
    await tap(tester, 'いま');
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.byType(JourneyScreen), findsNothing);
  });
  testWidgets('empty list is honest and keeps bottom navigation', (
    tester,
  ) async {
    await tester.pumpWidget(const MyApp(home: WatchScreen(pets: [])));
    expect(find.text('まだ旅立ったペットはいません'), findsOneWidget);
    expect(find.text('ミロ'), findsNothing);
    expect(find.text('ポポ'), findsNothing);
    expect(find.text('いま'), findsOneWidget);
  });
  testWidgets(
    'letter action explains pending screen without claiming delivery',
    (tester) async {
      await tester.pumpWidget(const MyApp(home: WatchScreen()));
      await tap(tester, '届いた手紙を見る');
      expect(find.text('届いた手紙を読む画面は準備中です。'), findsOneWidget);
      await tap(tester, '閉じる');
      expect(find.text('旅先のペットたち'), findsOneWidget);
    },
  );
  testWidgets('watch and selected journey scroll at large text sizes', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.view.reset);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await tester.pumpWidget(const MyApp(home: WatchScreen()));
    await tap(tester, 'ポポのようすを見る');
    await tap(tester, '見守る一覧に戻る');
    await tap(tester, '届いた手紙を見る');
    await tap(tester, '閉じる');
    expect(tester.takeException(), isNull);
  });
  testWidgets('watch list and pet journey visual previews', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(const MyApp(home: WatchScreen()));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(MyApp),
      matchesGoldenFile('watch_preview.png'),
    );
    await tap(tester, 'ミロのようすを見る');
    await expectLater(
      find.byType(WatchPetScreen),
      matchesGoldenFile('watch_pet_preview.png'),
    );
  });
}
