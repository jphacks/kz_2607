import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';

void main() {
  test('authentication completes before registering a device', () async {
    var authenticated = false;
    final service = CloudFunctionsService(
      prepare: () async {
        await Future<void>.delayed(Duration.zero);
        authenticated = true;
      },
      invoke: (name, data, _) async {
        expect(authenticated, true);
        expect(name, 'registerDevice');
        return {'deviceId': data['deviceId'], 'petId': 'pet-1'};
      },
    );
    expect(await service.registerDevice('AABBCCDDEE01'), 'pet-1');
  });
  test('failed authentication prevents registration', () async {
    var called = false;
    final service = CloudFunctionsService(
      prepare: () async => throw StateError('auth failed'),
      invoke: (_, _, _) async {
        called = true;
        return null;
      },
    );
    await expectLater(service.registerDevice('AABBCCDDEE01'), throwsStateError);
    expect(called, false);
  });
  test('invalid registration response is rejected', () async {
    final service = CloudFunctionsService(
      prepare: () async {},
      invoke: (_, _, _) async => {'deviceId': 'wrong', 'petId': 'pet-1'},
    );
    await expectLater(
      service.registerDevice('AABBCCDDEE01'),
      throwsFormatException,
    );
  });
}
