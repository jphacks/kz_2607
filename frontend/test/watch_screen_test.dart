import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/watch_screen.dart';
import 'package:kz_2607/journey_detail_screen.dart';
import 'package:kz_2607/foundation/controllers/watch_controller.dart';
import 'foundation/services/watch_controller_test.dart'
    show firstPetFixture, watchApi;
import 'home_screen_test.dart' show loadHomeFont;

void main() {
  setUpAll(loadHomeFont);
  Future<void> open(WidgetTester tester, String label) async {
    await tester.ensureVisible(find.text(label).last);
    await tester.pumpAndSettle();
    await tester.tap(find.text(label).last);
    await tester.pumpAndSettle();
  }

  testWidgets(
    'keeps existing watch layout and filters each detail by generation',
    (tester) async {
      final controller = WatchController(
        api: watchApi(() async => firstPetFixture()),
      );
      addTearDown(controller.dispose);
      await tester.pumpWidget(
        MaterialApp(home: WatchScreen(controller: controller)),
      );
      await tester.pumpAndSettle();
      expect(find.text('モチ'), findsOneWidget);
      expect(find.text('ミロ'), findsNothing);
      for (final entry in {
        'はじまり': '一緒に散歩した',
        'つながる思い出': 'あのお店で遊んだ',
        'いま': '今日もおしゃべりした',
      }.entries) {
        // "いま" also exists in bottom navigation; select the history label first.
        final label = find.text(entry.key).first;
        await tester.ensureVisible(label);
        await tester.pumpAndSettle();
        await tester.tap(label);
        await tester.pumpAndSettle();
        expect(find.byType(JourneyDetailScreen), findsOneWidget);
        await tester.scrollUntilVisible(
          find.text(entry.value),
          120,
          scrollable: find.byType(Scrollable).last,
        );
        expect(find.text(entry.value), findsOneWidget);
        final texts = ['一緒に散歩した', 'あのお店で遊んだ', '今日もおしゃべりした'];
        for (final text in texts.where((text) => text != entry.value)) {
          expect(find.text(text), findsNothing);
        }
        await tester.pageBack();
        await tester.pumpAndSettle();
      }
    },
  );
  testWidgets('empty first pet is not replaced with a sample', (tester) async {
    final controller = WatchController(
      api: watchApi(
        () async => {'petId': null, 'withYou': false, 'memories': []},
      ),
    );
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      MaterialApp(home: WatchScreen(controller: controller)),
    );
    await tester.pumpAndSettle();
    expect(find.text('まだ最初の子の情報がありません'), findsOneWidget);
    expect(find.text('ミロ'), findsNothing);
    expect(find.text('旅の履歴'), findsNothing);
  });
  testWidgets('large text remains scrollable', (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.view.reset);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final controller = WatchController(
      api: watchApi(() async => firstPetFixture()),
    );
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      MaterialApp(home: WatchScreen(controller: controller)),
    );
    await tester.pumpAndSettle();
    await open(tester, 'つながる思い出');
    expect(tester.takeException(), isNull);
  });
}
