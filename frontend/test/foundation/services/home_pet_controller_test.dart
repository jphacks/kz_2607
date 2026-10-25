import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:kz_2607/foundation/controllers/home_pet_controller.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';

Map<String, dynamic> pet(String device, String id, double gauge) => {
  'deviceId': device,
  'petId': id,
  'name': 'モチ',
  'generation': 2,
  'gauge': gauge,
  'birthStatus': 'born',
  'createdAt': '2026-10-24T00:00:00Z',
  'birthProfile': {'description': '元気な子', 'speechNote': 'やさしく話す'},
  'firstPerson': 'ぼく',
  'learnedWords': ['ありがとう'],
};

void main() {
  test(
    'birth name and server gauge refresh after conversation without local increments',
    () async {
      var gauge = 0.0;
      final controller = HomePetController(
        api: CloudFunctionsService(
          prepare: () async {},
          invoke: (name, args, _) async {
            expect(name, 'getPet');
            return pet(args['deviceId'] as String, 'pet-a', gauge);
          },
        ),
      );
      addTearDown(controller.dispose);
      controller.bind('device', 'pet-a');
      await Future<void>.delayed(Duration.zero);
      expect(controller.pet!.name, 'モチ');
      expect(controller.pet!.gauge, 0);
      gauge = 1;
      await controller.refresh();
      expect(controller.pet!.gauge, 1);
      expect(controller.pet!.generation, 2);
      expect(controller.pet!.description, '元気な子');
    },
  );

  test('old device response cannot overwrite the exchanged pet', () async {
    final old = Completer<Object?>();
    final controller = HomePetController(
      api: CloudFunctionsService(
        prepare: () async {},
        invoke: (_, args, _) async => args['deviceId'] == 'old-device'
            ? old.future
            : pet('new-device', 'new-pet', 0),
      ),
    );
    addTearDown(controller.dispose);
    controller.bind('old-device', 'old-pet');
    await Future<void>.delayed(Duration.zero);
    controller.bind('new-device', 'new-pet');
    await Future<void>.delayed(Duration.zero);
    old.complete(pet('old-device', 'old-pet', 1));
    await Future<void>.delayed(Duration.zero);
    expect(controller.pet!.petId, 'new-pet');
    expect(controller.pet!.gauge, 0);
    controller.bind(null, null);
    expect(controller.pet, isNull);
  });

  test(
    'permission error clears stale data and exposes code and reason',
    () async {
      var denied = false;
      final controller = HomePetController(
        api: CloudFunctionsService(
          prepare: () async {},
          invoke: (_, _, _) async {
            if (denied) {
              throw FirebaseFunctionsException(
                code: 'permission-denied',
                message: 'denied',
                details: {'reason': 'not_owner'},
              );
            }
            return pet('device', 'pet-a', 0.5);
          },
        ),
      );
      addTearDown(controller.dispose);
      controller.bind('device', 'pet-a');
      await Future<void>.delayed(Duration.zero);
      denied = true;
      await controller.refresh();
      expect(controller.pet, isNull);
      expect(controller.diagnostic, contains('permission-denied'));
      expect(controller.diagnostic, contains('not_owner'));
    },
  );

  test(
    'a refresh during an in-flight read is performed again for latest birth state',
    () async {
      final first = Completer<Object?>();
      var calls = 0;
      final controller = HomePetController(
        api: CloudFunctionsService(
          prepare: () async {},
          invoke: (_, _, _) async {
            calls++;
            return calls == 1 ? first.future : pet('device', 'pet-a', 1);
          },
        ),
      );
      addTearDown(controller.dispose);
      controller.bind('device', 'pet-a');
      await Future<void>.delayed(Duration.zero);
      await controller.refresh();
      first.complete(pet('device', 'pet-a', 0));
      await Future<void>.delayed(Duration.zero);
      expect(calls, 2);
      expect(controller.pet!.gauge, 1);
    },
  );
}
