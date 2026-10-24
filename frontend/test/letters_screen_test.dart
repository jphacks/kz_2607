import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/main.dart';
import 'package:kz_2607/letters_screen.dart';
import 'package:kz_2607/letter_detail_screen.dart';
import 'package:kz_2607/foundation/controllers/letters_controller.dart';
import 'foundation/services/letters_test.dart' show lettersApi, letterData;
import 'home_screen_test.dart' show loadHomeFont;

void main() {
  setUpAll(() async {
    await loadHomeFont();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });
  Future<LettersController> show(
    WidgetTester tester,
    Future<Object?> Function() data,
  ) async {
    final controller = LettersController(api: lettersApi(data));
    addTearDown(controller.dispose);
    await tester.pumpWidget(MyApp(home: LettersScreen(controller: controller)));
    await tester.pumpAndSettle();
    return controller;
  }

  testWidgets('selected letter opens full body with no reply operation', (
    tester,
  ) async {
    await show(
      tester,
      () async => {
        'firstPetId': 'first',
        'letters': [letterData()],
      },
    );
    await tester.tap(find.text('手紙をひらく'));
    await tester.pumpAndSettle();
    expect(find.byType(LetterDetailScreen), findsOneWidget);
    expect(find.text('ミロからの手紙'), findsOneWidget);
    expect(find.byType(SelectableText), findsNWidgets(2));
    expect(find.text('返信'), findsNothing);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('1通の旅の便り'), findsOneWidget);
  });
  testWidgets('empty inbox shows waiting state without made-up letters', (
    tester,
  ) async {
    await show(tester, () async => {'firstPetId': null, 'letters': []});
    expect(find.text('まだ手紙は届いていません'), findsOneWidget);
    expect(find.text('手紙をひらく'), findsNothing);
  });
  testWidgets('missing first pet metadata shows error and retry recovers', (
    tester,
  ) async {
    var supported = false;
    await show(
      tester,
      () async => {
        'ifUnused': null,
        if (supported) 'firstPetId': 'first',
        'letters': [letterData()],
      },
    );
    expect(find.text('手紙をひらく'), findsNothing);
    expect(find.text('もう一度読み込む'), findsOneWidget);
    supported = true;
    await tester.ensureVisible(find.text('もう一度読み込む'));
    await tester.tap(find.text('もう一度読み込む'));
    await tester.pumpAndSettle();
    expect(find.text('手紙をひらく'), findsOneWidget);
  });
  testWidgets('loading is visible and disables refresh', (tester) async {
    final pending = Completer<Object?>();
    final controller = LettersController(api: lettersApi(() => pending.future));
    addTearDown(controller.dispose);
    await tester.pumpWidget(MyApp(home: LettersScreen(controller: controller)));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    final button = tester.widget<IconButton>(find.byType(IconButton).first);
    expect(button.onPressed, isNull);
    pending.complete({'letters': []});
    await tester.pumpAndSettle();
  });
  testWidgets('long letter stays readable at large text sizes', (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.view.reset);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await show(
      tester,
      () async => {
        'firstPetId': 'first',
        'letters': [
          {
            ...letterData(),
            'body': List.filled(30, '旅先でも、元気にしているよ。').join('\n'),
          },
        ],
      },
    );
    await tester.scrollUntilVisible(
      find.text('手紙をひらく'),
      120,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('手紙をひらく'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('— ミロ'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
  testWidgets('letters visual previews with fixture data', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await show(
      tester,
      () async => {
        'firstPetId': 'first',
        'letters': [letterData()],
      },
    );
    await expectLater(
      find.byType(MyApp),
      matchesGoldenFile('letters_preview.png'),
    );
    await tester.tap(find.text('手紙をひらく'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(LetterDetailScreen),
      matchesGoldenFile('letter_detail_preview.png'),
    );
  });
}
