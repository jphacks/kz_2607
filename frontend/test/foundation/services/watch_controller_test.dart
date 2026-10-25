import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:kz_2607/foundation/controllers/watch_controller.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';
import 'package:kz_2607/foundation/watch_pet.dart';

Map<String, dynamic> firstPetFixture() => {
  'petId': 'first-pet',
  'name': 'モチ',
  'generation': 4,
  'stage': 'baby',
  'withYou': false,
  'appearance': {
    'primary': 'activity',
    'secondary': 'logical',
    'tertiary': 'curious',
    'stage': 'baby',
    'key': 'activity_logical_baby',
    'fallbackKey': 'activity_baby',
  },
  'memories': [
    {
      'generation': 1,
      'mine': true,
      'items': [
        {'text': '一緒に散歩した', 'createdAt': '2026-10-24T03:00:00Z'},
      ],
    },
    {
      'generation': 2,
      'mine': false,
      'items': [
        {'text': 'あのお店で遊んだ', 'createdAt': null},
      ],
    },
    {
      'generation': 4,
      'mine': false,
      'items': [
        {'text': '今日もおしゃべりした', 'createdAt': '2026-10-25T03:00:00Z'},
      ],
    },
  ],
};
CloudFunctionsService watchApi(Future<Object?> Function() response) =>
    CloudFunctionsService(
      prepare: () async {},
      invoke: (name, args, timeout) async {
        expect(name, 'getFirstPet');
        expect(args, isEmpty);
        expect(timeout, const Duration(seconds: 30));
        return response();
      },
    );

void main() {
  test(
    'reads only first pet without device registration and retains server text',
    () async {
      final controller = WatchController(
        api: watchApi(() async => firstPetFixture()),
      );
      addTearDown(controller.dispose);
      await controller.load();
      expect(controller.pet!.petId, 'first-pet');
      expect(controller.pet!.currentGeneration, 4);
      expect(controller.pet!.appearance.tertiary, 'curious');
      expect(controller.pet!.memories.map((m) => m.body), [
        '一緒に散歩した',
        'あのお店で遊んだ',
        '今日もおしゃべりした',
      ]);
    },
  );
  test(
    'no first pet remains empty, never falls back to sample or current pet',
    () async {
      final controller = WatchController(
        api: watchApi(
          () async => {'petId': null, 'withYou': false, 'memories': []},
        ),
      );
      addTearDown(controller.dispose);
      await controller.load();
      expect(controller.pet, isNull);
      expect(controller.error, isNull);
    },
  );
  test(
    'invalid response, auth error, then retry have distinct states',
    () async {
      var attempt = 0;
      final controller = WatchController(
        api: watchApi(() async {
          attempt++;
          if (attempt == 1) return {'petId': 'broken'};
          if (attempt == 2) {
            throw FirebaseFunctionsException(
              code: 'unauthenticated',
              message: 'login',
              details: {'reason': 'expired'},
            );
          }
          return firstPetFixture();
        }),
      );
      addTearDown(controller.dispose);
      await controller.load();
      expect(controller.diagnostic, contains('invalid_response'));
      await controller.load();
      expect(controller.diagnostic, contains('unauthenticated'));
      expect(controller.diagnostic, contains('expired'));
      await controller.load();
      expect(controller.pet!.name, 'モチ');
      expect(controller.error, isNull);
    },
  );
  test(
    'in-flight reload is deduplicated and disposed response is ignored',
    () async {
      final pending = Completer<Object?>();
      var calls = 0;
      final controller = WatchController(
        api: watchApi(() {
          calls++;
          return pending.future;
        }),
      );
      final first = controller.load();
      await controller.load();
      await Future<void>.delayed(Duration.zero);
      expect(calls, 1);
      controller.dispose();
      pending.complete(firstPetFixture());
      await first;
      expect(controller.pet, isNull);
    },
  );
  test(
    'invalid future generation and inconsistent appearance are rejected',
    () {
      final fixture = firstPetFixture();
      fixture['generation'] = 1;
      expect(() => WatchPet.fromResponse(fixture), throwsFormatException);
    },
  );
}
