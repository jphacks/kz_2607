import 'dart:async';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/cloud_functions_screen.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';

void main() {
  test('authentication completes before callable is invoked', () async {
    var authenticated = false;
    final service = CloudFunctionsService(
      prepare: () async {
        await Future<void>.delayed(Duration.zero);
        authenticated = true;
      },
      invokePing: () async {
        expect(authenticated, isTrue);
        return {'ok': true};
      },
    );
    await service.ping();
  });
  test('failed authentication prevents invoking a function', () async {
    var called = false;
    final service = CloudFunctionsService(
      prepare: () async => throw StateError('auth failed'),
      invokePing: () async {
        called = true;
        return {'ok': true};
      },
    );
    await expectLater(service.ping(), throwsStateError);
    expect(called, isFalse);
  });
  test('invalid ping replies are not reported as success', () async {
    for (final value in [
      null,
      {'ok': false},
      {'ok': 'true'},
      ['ok'],
    ]) {
      final service = CloudFunctionsService(
        prepare: () async {},
        invokePing: () async => value,
      );
      await expectLater(service.ping(), throwsFormatException);
    }
  });
  testWidgets('ping starts automatically once and shows successful response', (
    tester,
  ) async {
    final request = Completer<Object?>();
    var calls = 0;
    final service = CloudFunctionsService(
      prepare: () async {},
      invokePing: () {
        calls++;
        return request.future;
      },
    );
    await tester.pumpWidget(
      MaterialApp(home: CloudFunctionsScreen(service: service)),
    );
    await tester.pump();
    expect(
      tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
      isNull,
    );
    expect(calls, 1);
    request.complete({'ok': true});
    await tester.pumpAndSettle();
    expect(find.text('疎通確認成功：ping → {ok: true}'), findsOneWidget);
    expect(
      tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
      isNotNull,
    );
  });
  testWidgets('callable code and reason displayed and retry is possible', (
    tester,
  ) async {
    var calls = 0;
    final service = CloudFunctionsService(
      prepare: () async {},
      invokePing: () async {
        calls++;
        if (calls > 1) return {'ok': true};
        throw FirebaseFunctionsException(
          code: 'failed-precondition',
          message: 'Test failure',
          details: {'reason': 'example_reason'},
        );
      },
    );
    await tester.pumpWidget(
      MaterialApp(home: CloudFunctionsScreen(service: service)),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('code: failed-precondition'), findsOneWidget);
    expect(find.textContaining('reason: example_reason'), findsOneWidget);
    await tester.tap(find.text('再確認'));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('疎通確認成功：ping → {ok: true}'), findsOneWidget);
    expect(
      tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
      isNotNull,
    );
  });
  testWidgets('leaving screen before reply does not update disposed state', (
    tester,
  ) async {
    final request = Completer<Object?>();
    final service = CloudFunctionsService(
      prepare: () async {},
      invokePing: () => request.future,
    );
    await tester.pumpWidget(
      MaterialApp(home: CloudFunctionsScreen(service: service)),
    );
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    request.complete({'ok': true});
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
