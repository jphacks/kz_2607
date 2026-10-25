import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/main.dart';
import 'package:kz_2607/home_screen.dart';
import 'package:kz_2607/watch_screen.dart';
import 'package:kz_2607/designsystem/pet_portrait.dart';
import 'home_screen_test.dart' show loadHomeFont;

void main() {
  setUpAll(() async {
    await loadHomeFont();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });
  Future<void> tap(WidgetTester tester, String label) async {
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text(label).last);
    await tester.pumpAndSettle();
    await tester.tap(find.text(label).last);
    await tester.pumpAndSettle();
  }

  testWidgets(
    'watch combines first pet portrait and history without action buttons',
    (tester) async {
      await tester.pumpWidget(const MyApp(home: HomeScreen()));
      expect(find.text('M5に接続すると、この子の情報を表示します。'), findsOneWidget);
      await tap(tester, '見守る');
      expect(find.text('ミロ'), findsOneWidget);
      expect(find.byType(PetPortrait), findsOneWidget);
      expect(find.text('旅の履歴'), findsOneWidget);
      expect(find.text('あなたが最初の飼い主として、この子を育てました。'), findsOneWidget);
      expect(find.byType(FilledButton), findsNothing);
      expect(find.text('ポポ'), findsNothing);
      expect(find.text('ミロの旅を見る'), findsNothing);
      expect(find.text('ミロからの手紙を見る'), findsNothing);
      await tap(tester, 'いま');
      expect(find.byType(HomeScreen), findsOneWidget);
      expect(find.byType(WatchScreen), findsNothing);
    },
  );
  testWidgets('unknown first pet stays empty on watch', (tester) async {
    await tester.pumpWidget(const MyApp(home: HomeScreen(firstPet: null)));
    await tap(tester, '見守る');
    expect(find.text('まだ最初の子の情報がありません'), findsOneWidget);
    expect(find.byType(PetPortrait), findsNothing);
    expect(find.text('旅の履歴'), findsNothing);
  });
  testWidgets('large text watch remains scrollable without overflow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.view.reset);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    await tap(tester, '見守る');
    await tester.scrollUntilVisible(
      find.text('2代目からの思い出'),
      150,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
    await tap(tester, 'いま');
    expect(tester.takeException(), isNull);
  });
  testWidgets('watch visual preview', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    await tap(tester, '見守る');
    await expectLater(
      find.byType(WatchScreen),
      matchesGoldenFile('watch_preview.png'),
    );
  });
}
