import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:kz_2607/exchange_result_screen.dart';
import 'package:kz_2607/foundation/controllers/exchange_controller.dart';
import 'package:kz_2607/foundation/services/core2_ble.dart';

Map<String, dynamic> record(
  String transaction, {
  String result = 'done',
  bool acked = false,
}) => {
  'exchange': {
    'transactionId': transaction,
    'myDeviceId': 'AABBCCDDEEFF',
    'peerDeviceId': '112233445566',
    'givenPetId': 'pet-a',
    'gotPetId': 'pet-b',
    'distanceMeters': 0.1,
  },
  'result': result,
  'acked': acked,
};

void main() {
  testWidgets(
    'restored server decision is not shown as M5 completion without ACK',
    (tester) async {
      SharedPreferences.setMockInitialValues({
        'exchange_journal_v2_user': jsonEncode({
          '0123456789ABCDEF': record('0123456789ABCDEF'),
        }),
      });
      final controller = ExchangeController('user');
      await controller.ready;
      final ble = Core2Ble()..exchange = controller;
      addTearDown(ble.dispose);
      await tester.pumpWidget(
        MaterialApp(home: ExchangeResultScreen(ble: ble)),
      );
      expect(find.text('交換確定・M5への反映待ち'), findsOneWidget);
      expect(find.text('交換完了'), findsNothing);
      expect(find.text('pet-a'), findsOneWidget);
      expect(find.text('pet-b'), findsOneWidget);
      await tester.ensureVisible(find.text('交換結果を再確認'));
      expect(
        tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
        isNull,
      );
      expect(tester.takeException(), isNull);
    },
  );

  test(
    'restored journal exposes all records newest received first with cancellation distinguished',
    () async {
      SharedPreferences.setMockInitialValues({
        'exchange_journal_v2_user': jsonEncode({
          '0123456789ABCDEF': record('0123456789ABCDEF', acked: true),
          '1123456789ABCDEF': record(
            '1123456789ABCDEF',
            result: 'rejected',
            acked: true,
          ),
        }),
      });
      final controller = ExchangeController('user');
      addTearDown(controller.dispose);
      await controller.ready;
      expect(controller.records.map((record) => record.status), [
        '取消完了',
        '交換完了',
      ]);
      expect(
        controller.records.first.exchange.transactionId,
        '1123456789ABCDEF',
      );
      expect(() => controller.records.clear(), throwsUnsupportedError);
    },
  );

  testWidgets(
    'without an active exchange session prompts connection without fabricated results',
    (tester) async {
      final ble = Core2Ble();
      addTearDown(ble.dispose);
      await tester.pumpWidget(
        MaterialApp(home: ExchangeResultScreen(ble: ble)),
      );
      expect(find.text('M5に接続すると、保存済みの交換結果を確認できます。'), findsOneWidget);
      expect(find.text('交換完了'), findsNothing);
    },
  );
}
