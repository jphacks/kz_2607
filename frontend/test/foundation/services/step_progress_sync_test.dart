import 'package:cloud_functions/cloud_functions.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';
import 'package:kz_2607/foundation/services/step_progress_sync.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('sends observed daily increments and resumes after app restart', () async {
    SharedPreferences.setMockInitialValues({});
    var now = DateTime.utc(2026, 10, 25, 1);
    final sent = <Map<String, Object?>>[];
    final api = CloudFunctionsService(
      prepare: () async {},
      invoke: (name, args, _) async {
        expect(name, 'recordProgress');
        sent.add(args);
        return {'status': 'ok', 'date': args['date']};
      },
    );
    StepProgressSync sync() => StepProgressSync(api: api, now: () => now);
    Future<void> observe(StepProgressSync service, int count) => service.observe(
          uid: 'user-1', deviceId: 'AABBCCDDEEFF', petId: 'pet-1',
          cumulative: count,
        );

    final first = sync();
    await observe(first, 1000); // First total is a baseline, not today's count.
    expect(sent, isEmpty);
    await observe(first, 1012);
    expect(sent.single['steps'], 12);

    final restarted = sync();
    now = now.add(const Duration(minutes: 2));
    await observe(restarted, 1020);
    expect(sent.last['steps'], 20); // Send the daily total, not a delta of 8.
    expect(sent.last['date'], '2026-10-25');

    now = DateTime.utc(2026, 10, 25, 15, 1); // 00:01 JST next day.
    await observe(restarted, 1030);
    expect(sent.length, 2); // Overnight steps cannot be assigned to a day.
    now = now.add(const Duration(minutes: 2));
    await observe(restarted, 1035);
    expect(sent.last['date'], '2026-10-26');
    expect(sent.last['steps'], 5);
  });

  test('retains unsent steps for a later retry', () async {
    SharedPreferences.setMockInitialValues({});
    var now = DateTime.utc(2026, 10, 25, 1);
    var attempts = 0;
    final api = CloudFunctionsService(
      prepare: () async {},
      invoke: (_, args, __) async {
        attempts++;
        if (attempts == 1) throw StateError('offline');
        expect(args['steps'], 7);
        return {'status': 'ok', 'date': args['date']};
      },
    );
    final sync = StepProgressSync(api: api, now: () => now);
    Future<void> observe(int count) => sync.observe(
          uid: 'user-1', deviceId: 'AABBCCDDEEFF', petId: 'pet-1',
          cumulative: count,
        );
    await observe(100);
    await expectLater(observe(107), throwsStateError);
    now = now.add(const Duration(minutes: 2));
    await sync.flush(uid: 'user-1', deviceId: 'AABBCCDDEEFF', petId: 'pet-1');
    expect(attempts, 2);
  });

  test('retries only the callable integer serialization error', () async {
    var fallbackCalls = 0;
    final api = CloudFunctionsService(
      prepare: () async {},
      invoke: (name, args, _) async {
        expect(name, 'recordProgress');
        expect(args['steps'], isA<int>());
        throw FirebaseFunctionsException(
          code: 'invalid-argument',
          message: 'steps は、0〜200000 の整数にしてください',
        );
      },
      progressFallback: (args) async {
        fallbackCalls++;
        expect(args['steps'], 7);
        return {'status': 'ok', 'date': args['date']};
      },
    );
    await api.recordProgress(deviceId: 'AABBCCDDEEFF',
        date: '2026-10-25', steps: 7);
    expect(fallbackCalls, 1);
  });
}
