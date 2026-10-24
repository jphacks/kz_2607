import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/main.dart';
import 'package:kz_2607/home_screen.dart';
import 'home_screen_test.dart' show loadHomeFont;

void main() {
  testWidgets('home visual preview', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await loadHomeFont();
    await tester.pumpWidget(const MyApp(home: HomeScreen()));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(MyApp),
      matchesGoldenFile('home_preview.png'),
    );
  });
}
