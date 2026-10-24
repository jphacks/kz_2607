import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/controllers/exchange_controller.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('persisted confirmed result is replayed after a lost Core2 ACK', () async {
    SharedPreferences.setMockInitialValues({});
    const uid = 'test-user';
    const tx = '0123456789ABCDEF';
    const own = 'AABBCCDDEEFF';
    var reports = 0;
    final api = CloudFunctionsService(
      prepare: () async {},
      invoke: (name, args, timeout) async {
        if (name == 'reportExchange') {
          reports++;
          final prefs = await SharedPreferences.getInstance();
          final journal = jsonDecode(prefs.getString('exchange_journal_v2_$uid')!) as Map;
          expect((journal[tx] as Map)['acked'], false);
          return {
            'status': 'done', 'transactionId': tx,
            'givenPetId': 'pet-a', 'receivedPetId': 'pet-b',
          };
        }
        if (name == 'registerDevice') {
          return {'deviceId': own, 'petId': 'pet-b'};
        }
        fail('Unexpected callable: $name');
      },
    );
    final candidate = <String, dynamic>{
      'type': 'exchange_pending', 'transactionId': tx,
      'myDeviceId': own, 'peerDeviceId': '112233445566',
      'givenPetId': 'pet-a', 'gotPetId': 'pet-b',
      'distanceMeters': 0.1,
    };
    final first = ExchangeController(uid, api: api);
    await first.ready;
    first.connectedDevice(own);
    expect(await first.receive(candidate, own), isTrue);
    await first.process((_) async => throw StateError('BLE disconnected'));
    expect(first.hasUnresolved, isTrue);
    expect(reports, 1);
    first.dispose();

    final restored = ExchangeController(uid, api: api);
    await restored.ready;
    expect(restored.candidate?.transactionId, tx);
    restored.connectedDevice(own);
    Map<String, dynamic>? sent;
    await restored.process((message) async { sent = message; });
    expect(sent?['result'], 'done');
    expect(restored.deliveredPetId, 'pet-b');
    expect(restored.hasUnresolved, isFalse);
    expect(reports, 1);
    restored.dispose();
  });
}
