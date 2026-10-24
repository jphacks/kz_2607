import 'dart:async';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/controllers/letters_controller.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';

Map<String, Object?> letterData({
  String pet = 'first',
  String id = 'letter-1',
  String date = '2026-10-25T00:00:00Z',
}) => {
  'letterId': id,
  'petId': pet,
  'petName': 'ミロ',
  'title': '旅先からの便り',
  'body': '元気にしているよ。\nありがとうも、覚えているよ。',
  'generation': 3,
  'createdAt': date,
};
CloudFunctionsService lettersApi(Future<Object?> Function() result) =>
    CloudFunctionsService(
      prepare: () async {},
      invoke: (name, args, timeout) {
        expect(name, 'getLetters');
        expect(args, isEmpty);
        expect(timeout.inSeconds, 30);
        return result();
      },
    );

void main() {
  test(
    'getLetters authenticates before invoking callable and sorts newest first',
    () async {
      var authenticated = false;
      final api = CloudFunctionsService(
        prepare: () async {
          authenticated = true;
        },
        invoke: (name, args, timeout) async {
          expect(authenticated, true);
          expect(name, 'getLetters');
          expect(args, isEmpty);
          return {
            'firstPetId': 'first',
            'letters': [
              letterData(id: 'old', date: '2026-10-01T00:00:00Z'),
              letterData(id: 'new'),
            ],
          };
        },
      );
      expect((await api.getLetters()).letters.map((e) => e.letterId), [
        'new',
        'old',
      ]);
    },
  );
  test('only first-created pet letters enter display state', () async {
    final controller = LettersController(
      api: lettersApi(
        () async => {
          'firstPetId': 'first',
          'letters': [letterData(), letterData(pet: 'other')],
        },
      ),
    );
    await controller.load();
    expect(controller.letters.map((e) => e.petId), ['first']);
    expect(controller.error, isNull);
    controller.dispose();
  });
  test(
    'legacy nonempty response never guesses first pet from oldest letter',
    () async {
      final controller = LettersController(
        api: lettersApi(
          () async => {
            'letters': [letterData()],
          },
        ),
      );
      await controller.load();
      expect(controller.letters, isEmpty);
      expect(controller.diagnostic, contains('first_pet_id_missing'));
      controller.dispose();
    },
  );
  test('empty response remains a valid empty state', () async {
    final controller = LettersController(
      api: lettersApi(() async => {'firstPetId': null, 'letters': []}),
    );
    await controller.load();
    expect(controller.error, isNull);
    expect(controller.letters, isEmpty);
    controller.dispose();
  });
  test(
    'malformed letter is rejected rather than displayed as a valid empty inbox',
    () async {
      final controller = LettersController(
        api: lettersApi(
          () async => {
            'firstPetId': 'first',
            'letters': [
              {...letterData(), 'createdAt': 'invalid'},
            ],
          },
        ),
      );
      await controller.load();
      expect(controller.error, isNotNull);
      expect(controller.diagnostic, contains('invalid_response'));
      controller.dispose();
    },
  );
  test(
    'function failure preserves function code and reason and can be retried',
    () async {
      var fail = true;
      final controller = LettersController(
        api: lettersApi(() async {
          if (fail) {
            throw FirebaseFunctionsException(
              code: 'unavailable',
              details: {'reason': 'temporary'},
              message: 'offline',
            );
          }
          return {
            'firstPetId': 'first',
            'letters': [letterData()],
          };
        }),
      );
      await controller.load();
      expect(controller.diagnostic, contains('unavailable'));
      expect(controller.diagnostic, contains('temporary'));
      fail = false;
      await controller.load();
      expect(controller.error, isNull);
      expect(controller.letters.length, 1);
      controller.dispose();
    },
  );
  test(
    'concurrent reloads are suppressed and completion after dispose is ignored',
    () async {
      final pending = Completer<Object?>();
      var calls = 0;
      final controller = LettersController(
        api: lettersApi(() {
          calls++;
          return pending.future;
        }),
      );
      final loading = controller.load();
      await Future<void>.delayed(Duration.zero);
      await controller.load();
      expect(calls, 1);
      controller.dispose();
      pending.complete({'letters': []});
      await loading;
    },
  );
}
