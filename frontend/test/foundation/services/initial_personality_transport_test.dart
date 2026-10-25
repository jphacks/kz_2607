import 'dart:convert';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';

void main() {
  test(
    'invalid_answers retries once with identical integer JSON payload and request ID',
    () async {
      var calls = 0, retries = 0;
      Map<String, Object?>? original;
      final api = CloudFunctionsService(
        prepare: () async {},
        invoke: (name, data, timeout) async {
          calls++;
          original = Map.of(data);
          throw FirebaseFunctionsException(
            code: 'invalid-argument',
            message: 'answers は 0〜3 の整数にしてください',
            details: {'reason': 'invalid_answers'},
          );
        },
        initialPersonalityFallback: (data) async {
          retries++;
          expect(data, original);
          final wire = jsonDecode(jsonEncode({'data': data}))['data'] as Map;
          expect(wire['answers'], [3, 1, 0, 2, 1, 0]);
          expect(
            (wire['answers'] as List).every((value) => value is int),
            isTrue,
          );
          expect(wire['requestId'], 'same-request');
          expect(wire['questionnaireVersion'], 'birth_v1_6q4');
          return {'status': 'ok', 'petId': 'pet-a'};
        },
      );
      final result = await api.setInitialPersonality(
        deviceId: 'device',
        answers: [3, 1, 0, 2, 1, 0],
        requestId: 'same-request',
      );
      expect(result['status'], 'ok');
      expect(calls, 1);
      expect(retries, 1);
    },
  );

  test(
    'out of range and missing answers never reach authentication or transport',
    () async {
      final api = CloudFunctionsService(
        prepare: () async =>
            fail('invalid local payload must not authenticate'),
        invoke: (_, _, _) async => fail('invalid local payload must not send'),
      );
      for (final answers in [
        [0, 1, 2, 3, 4, 0],
        [0, 1],
        [-1, 0, 0, 0, 0, 0],
      ]) {
        await expectLater(
          api.setInitialPersonality(
            deviceId: 'device',
            answers: answers,
            requestId: 'same',
          ),
          throwsFormatException,
        );
      }
    },
  );

  test('unrelated API errors do not retry', () async {
    for (final error in [
      FirebaseFunctionsException(
        code: 'permission-denied',
        message: 'denied',
        details: {'reason': 'invalid_answers'},
      ),
      FirebaseFunctionsException(
        code: 'invalid-argument',
        message: 'invalid',
        details: {'reason': 'invalid_version'},
      ),
    ]) {
      final api = CloudFunctionsService(
        prepare: () async {},
        invoke: (_, _, _) async => throw error,
        initialPersonalityFallback: (_) async =>
            fail('unrelated errors must not retry'),
      );
      await expectLater(
        api.setInitialPersonality(
          deviceId: 'device',
          answers: List.filled(6, 0),
          requestId: 'same',
        ),
        throwsA(same(error)),
      );
    }
  });

  test(
    'a rejected fallback surfaces its code and reason without another retry',
    () async {
      final rejection = FirebaseFunctionsException(
        code: 'invalid-argument',
        message: 'invalid',
        details: {'reason': 'invalid_answers'},
      );
      var retries = 0;
      final api = CloudFunctionsService(
        prepare: () async {},
        invoke: (_, _, _) async => throw rejection,
        initialPersonalityFallback: (_) async {
          retries++;
          throw rejection;
        },
      );
      await expectLater(
        api.setInitialPersonality(
          deviceId: 'device',
          answers: List.filled(6, 0),
          requestId: 'same',
        ),
        throwsA(same(rejection)),
      );
      expect(retries, 1);
    },
  );
}
