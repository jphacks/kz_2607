import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:kz_2607/birth_screen.dart';
import 'package:kz_2607/foundation/models/birth_questionnaire.dart';
import 'package:kz_2607/foundation/services/birth_service.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';

void main() {
  test(
    'display order is converted to backend order and values stay within range',
    () {
      final answers = BirthAnswers([0, 1, 2, 3, 0, 1]);
      expect(answers.apiAnswers, [0, 3, 1, 2, 0, 1]);
      expect(answers.personalityAxes['friendly'], .8);
      expect(answers.personalityAxes['nightowl'], .4);
      expect(BirthAnswers(List.filled(6, 2)).birthTrait, 'active');
    },
  );

  test(
    'personality save sends device ID, canonical answers and stable request ID',
    () async {
      final calls = <String>[];
      final service = BirthService(
        api: CloudFunctionsService(
          prepare: () async {},
          invoke: (name, data, timeout) async {
            calls.add(name);
            if (name == 'getPet') {
              return {
                'deviceId': 'AABBCCDDEEFF',
                'petId': 'pet_a',
                'generation': 1,
                'birthStatus': 'egg',
              };
            }
            expect(data['deviceId'], 'AABBCCDDEEFF');
            expect(data['answers'], [0, 3, 1, 2, 0, 1]);
            expect(data['requestId'], 'request');
            expect(data.containsKey('axes'), false);
            return {
              'status': 'ok',
              'petId': 'pet_a',
              'birthStatus': 'personality_set',
              'alreadySet': true,
            };
          },
        ),
      );
      await service.setInitial(
        deviceId: 'AABBCCDDEEFF',
        petId: 'pet_a',
        requestId: 'request',
        answers: BirthAnswers([0, 1, 2, 3, 0, 1]),
      );
      expect(calls, ['getPet', 'setInitialPersonality']);
    },
  );

  test('changed registered pet prevents mutation', () async {
    final calls = <String>[];
    final service = BirthService(
      api: CloudFunctionsService(
        prepare: () async {},
        invoke: (name, data, timeout) async {
          calls.add(name);
          return {
            'deviceId': 'device',
            'petId': 'different',
            'generation': 1,
            'birthStatus': 'egg',
          };
        },
      ),
    );
    await expectLater(
      service.setInitial(
        deviceId: 'device',
        petId: 'pet_a',
        requestId: 'request',
        answers: BirthAnswers(List.filled(6, 0)),
      ),
      throwsStateError,
    );
    expect(calls, ['getPet']);
  });

  testWidgets('saved profile resumes at naming and confirms birth', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    var status = 'profile_ready';
    final profile = {
      'source': 'template',
      'nameCandidates': ['モチ', 'ポポ', 'ルル'],
      'description': '元気な子',
      'firstPerson': 'ぼく',
      'speechNote': '元気な話し方',
      'firstWords': 'はじめまして！',
    };
    final calls = <String>[];
    final service = BirthService(
      api: CloudFunctionsService(
        prepare: () async {},
        invoke: (name, data, timeout) async {
          calls.add(name);
          if (name == 'getPet') {
            return {
              'deviceId': 'device',
              'petId': 'pet_a',
              'generation': 1,
              'birthStatus': status,
              'birthProfile': profile,
              'name': status == 'born' ? 'モチ' : null,
            };
          }
          expect(name, 'setPetName');
          expect(data['name'], 'モチ');
          expect(data['firstPerson'], 'ぼく');
          status = 'born';
          return {
            'petId': 'pet_a',
            'name': 'モチ',
            'firstPerson': 'ぼく',
            'birthStatus': 'born',
            'firstWords': 'はじめまして！',
          };
        },
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: BirthScreen(
          deviceId: 'device',
          petId: 'pet_a',
          uid: 'user',
          service: service,
          canContinue: () => true,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('元気な子'), findsOneWidget);
    expect(find.textContaining('予備の設定'), findsOneWidget);
    expect(find.text(birthQuestions.first.title), findsNothing);
    await tester.ensureVisible(find.text('この名前で誕生する'));
    await tester.tap(find.text('この名前で誕生する'));
    await tester.pumpAndSettle();
    expect(find.text('モチが生まれました！'), findsOneWidget);
    expect(find.text('はじめまして！'), findsOneWidget);
    expect(calls.where((name) => name == 'generateBirthProfile'), isEmpty);
    expect(calls.where((name) => name == 'setPetName').length, 1);
  });
}
