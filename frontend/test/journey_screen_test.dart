import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/main.dart';
import 'package:kz_2607/home_screen.dart';
import 'package:kz_2607/journey_screen.dart';
import 'home_screen_test.dart' show loadHomeFont;

void main() {
  setUpAll(loadHomeFont);
  testWidgets('journey opens from home and returns without duplicating home', (
    tester,
  ) async {
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    await tester.tap(find.text('旅'));
    await tester.pumpAndSettle();
    expect(find.text('ポポの旅'), findsOneWidget);
    expect(find.text('旅の履歴・受け継いだもの（表示サンプル）'), findsOneWidget);
    await tester.tap(find.text('旅'));
    await tester.pumpAndSettle();
    expect(find.byType(JourneyScreen), findsOneWidget);
    await tester.tap(find.text('いま'));
    await tester.pumpAndSettle();
    expect(find.text('いま、一緒にいる子'), findsOneWidget);
    await tester.tap(find.text('旅'));
    await tester.pumpAndSettle();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('いま、一緒にいる子'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('journey scrolls with large text and keeps navigation usable', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    await tester.tap(find.text('旅'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('AIがつないだ思い出'),
      150,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.tap(find.text('見守る'));
    await tester.pumpAndSettle();
    expect(find.text('旅立ったペットの見守り画面は準備中です。'), findsOneWidget);
    await tester.tap(find.text('閉じる'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('いま'));
    await tester.pumpAndSettle();
    expect(find.text('いま、一緒にいる子'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('journey visual preview', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    await tester.tap(find.text('旅'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(JourneyScreen),
      matchesGoldenFile('journey_preview.png'),
    );
  });
}
