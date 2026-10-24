import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/models/pending_exchange.dart';
import 'package:kz_2607/foundation/services/exchange_resolver.dart';

Map<String, dynamic> candidate(double? distance) => {
  'type': 'exchange_pending',
  'transactionId': '0123456789ABCDEF',
  'myDeviceId': 'AABBCCDDEEFF',
  'peerDeviceId': '112233445566',
  'givenPetId': 'pet-a',
  'gotPetId': 'pet-b',
  if (distance != null) 'distanceMeters': distance,
};

void main() {
  test('only distances up to and including 0.1m qualify', () {
    expect(PendingExchange.fromMap(candidate(0.1)).distanceMeters, 0.1);
    for (final value in <double?>[null, 0, -0.1, 0.10001, double.nan]) {
      expect(
        () => PendingExchange.fromMap(candidate(value)),
        throwsFormatException,
      );
    }
  });

  test(
    'a valid report confirms only the expected pets and transaction',
    () async {
      final x = PendingExchange.fromMap(candidate(0.09));
      final calls = <String>[];
      final resolver = ExchangeResolver((name, args) async {
        calls.add(name);
        expect(args['transactionId'], x.transactionId);
        return {
          'status': 'done',
          'transactionId': x.transactionId,
          'givenPetId': x.givenPetId,
          'receivedPetId': x.gotPetId,
        };
      });
      final result = await resolver.resolve(x);
      expect(result.result, 'done');
      expect(calls, ['reportExchange']);
    },
  );

  test('an ambiguous failure is queried before cancellation', () async {
    final x = PendingExchange.fromMap(candidate(0.1));
    final calls = <String>[];
    final resolver = ExchangeResolver((name, args) async {
      calls.add(name);
      if (name == 'reportExchange') throw StateError('timeout');
      if (name == 'getExchangeResult') {
        return {
          'status': 'confirmed',
          'transactionId': x.transactionId,
          'givenPetId': x.givenPetId,
          'receivedPetId': x.gotPetId,
          'currentPetId': x.gotPetId,
        };
      }
      throw StateError('cancel must not be called');
    });
    expect((await resolver.resolve(x)).result, 'done');
    expect(calls, ['reportExchange', 'reportExchange', 'getExchangeResult']);
  });
}
