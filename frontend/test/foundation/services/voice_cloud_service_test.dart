import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';
import 'package:kz_2607/foundation/services/voice_cloud_service.dart';

Map<String, Object?> registration(String id) => {
  'deviceId': id,
  'petId': 'pet-1',
  'isNew': false,
};
Map<String, Object?> reply({
  String status = 'ok',
  String audioStatus = 'skipped',
}) => {
  'status': status,
  'transcript': status == 'no_speech' ? '' : 'こんにちは',
  'replyText': status == 'no_speech' ? '' : 'やあ',
  'audioStatus': audioStatus,
  'petId': 'pet-1',
  'learnedWords': ['こんにちは'],
  if (audioStatus == 'ok')
    'replyAudio': {
      'format': 'ima_adpcm',
      'sampleRate': 16000,
      'channels': 1,
      'sampleCount': 8,
    },
  if (audioStatus == 'ok') 'replyAudioBase64': base64Encode([82, 73, 70, 70]),
};
CloudFunctionsService api(
  Future<Object?> Function(String, Map<String, Object?>, Duration) call,
) => CloudFunctionsService(prepare: () async {}, invoke: call);

void main() {
  test(
    'permission-denied keeps diagnostic code and explains account ownership',
    () async {
      final cloud = VoiceCloudService(
        api: api((_, _, _) async {
          throw FirebaseFunctionsException(
            code: 'permission-denied',
            message: 'denied',
            details: {'reason': 'not_owner'},
          );
        }),
      );
      cloud.setConnection('AA:BB:CC:DD:EE:01');
      await cloud.enable();
      expect(cloud.enabled, false);
      expect(cloud.status, contains('code: permission-denied'));
      expect(cloud.status, contains('reason: not_owner'));
      expect(cloud.status, contains('端末を登録したアカウント'));
      cloud.dispose();
    },
  );
  test(
    'talk sends a real WAV as Base64 with device, pet and long callable timeout',
    () async {
      final service = api((name, data, timeout) async {
        expect(name, 'talkToPet');
        expect(timeout.inSeconds, 130);
        expect(data['deviceId'], 'core2-1');
        expect(data['petId'], 'pet-1');
        expect(data['wantAudio'], true);
        expect(data['replyFormat'], 'ima_adpcm');
        final bytes = base64Decode(data['audioBase64'] as String);
        expect(String.fromCharCodes(bytes.sublist(0, 4)), 'RIFF');
        final header = ByteData.sublistView(bytes);
        expect(header.getUint32(24, Endian.little), 16000);
        expect(header.getUint16(22, Endian.little), 1);
        expect(bytes.sublist(44), [0, 1, 2, 3]);
        return reply();
      });
      await service.talkToPet(
        deviceId: 'core2-1',
        petId: 'pet-1',
        pcm: Uint8List.fromList([0, 1, 2, 3]),
      );
    },
  );
  test('minimal backend no_speech reply is accepted', () async {
    final service = api(
      (_, _, _) async => {
        'status': 'no_speech',
        'transcript': '',
        'petId': 'pet-1',
        'durationSec': 1,
      },
    );
    final result = await service.talkToPet(
      deviceId: 'core2-1',
      petId: 'pet-1',
      pcm: Uint8List(10),
    );
    expect(result['status'], 'no_speech');
    expect(result['audioStatus'], 'skipped');
    expect(result['replyText'], '');
  });
  test(
    'BLE MAC is normalized and the same ID is used for registration and audio',
    () async {
      final cloud = VoiceCloudService(
        api: api((name, data, _) async {
          expect(data['deviceId'], 'AABBCCDDEE01');
          return name == 'registerDevice'
              ? registration(data['deviceId'] as String)
              : reply();
        }),
      );
      addTearDown(cloud.dispose);
      cloud.setConnection('aa:bb:cc:dd:ee:01');
      expect(cloud.connectionDeviceId, 'AABBCCDDEE01');
      await cloud.enable();
      await cloud.sendPcm(Uint8List(10));
      expect(cloud.deviceId, 'AABBCCDDEE01');
    },
  );
  test('missing or non-MAC connection cannot be registered', () async {
    var calls = 0;
    final cloud = VoiceCloudService(
      api: api((_, _, _) async {
        calls++;
        return null;
      }),
    );
    addTearDown(cloud.dispose);
    await cloud.enable();
    cloud.setConnection('unknown-device');
    await cloud.enable();
    expect(cloud.enabled, false);
    expect(cloud.connectionDeviceId, isNull);
    expect(calls, 0);
  });
  test(
    'received reply is automatically forwarded and busy remains true until Core2 ACK',
    () async {
      final done = Completer<void>();
      var forwarded = false;
      final cloud = VoiceCloudService(
        api: api(
          (name, data, _) async => name == 'registerDevice'
              ? registration(data['deviceId'] as String)
              : reply(audioStatus: 'ok'),
        ),
      );
      addTearDown(cloud.dispose);
      cloud.setConnection('AA:BB:CC:DD:EE:01');
      cloud.sendReply = (bytes, count) {
        expect(bytes.length, 4);
        expect(count, 8);
        forwarded = true;
        return done.future;
      };
      await cloud.enable();
      final sending = cloud.sendPcm(Uint8List(10));
      await Future<void>.delayed(Duration.zero);
      expect(forwarded, true);
      expect(cloud.busy, true);
      cloud.replyProgress(4, 4);
      expect(cloud.replySentBytes, 4);
      done.complete();
      await sending;
      expect(cloud.busy, false);
      expect(cloud.replyTransferStatus, contains('受信完了ACK'));
    },
  );
  test(
    'Core2 transfer failure preserves text and does not repeat the cloud call',
    () async {
      var calls = 0;
      final cloud = VoiceCloudService(
        api: api((name, data, _) async {
          if (name == 'registerDevice') {
            return registration(data['deviceId'] as String);
          }
          calls++;
          return reply(audioStatus: 'ok');
        }),
      );
      addTearDown(cloud.dispose);
      cloud.setConnection('AA:BB:CC:DD:EE:01');
      cloud.sendReply = (_, _) async => throw StateError('ACK timeout');
      await cloud.enable();
      await cloud.sendPcm(Uint8List(10));
      expect(cloud.replyText, 'やあ');
      expect(calls, 1);
      expect(cloud.replyTransferStatus, contains('失敗'));
    },
  );
  test(
    'disconnect during reply transfer cancels sender and discards completion',
    () async {
      final done = Completer<void>();
      var cancelled = false;
      final cloud = VoiceCloudService(
        api: api(
          (name, data, _) async => name == 'registerDevice'
              ? registration(data['deviceId'] as String)
              : reply(audioStatus: 'ok'),
        ),
      );
      addTearDown(cloud.dispose);
      cloud.setConnection('AA:BB:CC:DD:EE:01');
      cloud.sendReply = (_, _) => done.future;
      cloud.cancelReply = () {
        cancelled = true;
        done.completeError(StateError('closed'));
      };
      await cloud.enable();
      final sending = cloud.sendPcm(Uint8List(10));
      await Future<void>.delayed(Duration.zero);
      cloud.setConnection(null);
      await sending;
      expect(cancelled, true);
      expect(cloud.replyTransferStatus, isNull);
      expect(cloud.replyText, isNull);
      expect(cloud.enabled, false);
    },
  );
  test('connection starts registration automatically exactly once', () async {
    var calls = 0;
    final cloud = VoiceCloudService(
      api: api((name, data, _) async {
        calls++;
        return registration(data['deviceId'] as String);
      }),
    );
    addTearDown(cloud.dispose);
    cloud.startForConnection('AA:BB:CC:DD:EE:01');
    await Future<void>.delayed(Duration.zero);
    expect(cloud.enabled, true);
    expect(calls, 1);
    cloud.startForConnection('AA:BB:CC:DD:EE:01');
    await Future<void>.delayed(Duration.zero);
    expect(calls, 1);
  });
  test(
    'new connection automatically activates after an old request finishes',
    () async {
      var calls = 0;
      final pending = Completer<Object?>();
      final cloud = VoiceCloudService(
        api: api((name, data, _) async {
          calls++;
          return calls == 1
              ? pending.future
              : registration(data['deviceId'] as String);
        }),
      );
      addTearDown(cloud.dispose);
      cloud.startForConnection('AA:BB:CC:DD:EE:01');
      cloud.setConnection(null);
      cloud.startForConnection('AA:BB:CC:DD:EE:02');
      pending.complete(registration('AABBCCDDEE01'));
      await Future<void>.delayed(Duration.zero);
      expect(cloud.deviceId, 'AABBCCDDEE02');
      expect(calls, 2);
    },
  );
  test(
    'automatic registration error is shown without an endless retry loop',
    () async {
      var calls = 0;
      final cloud = VoiceCloudService(
        api: api((_, _, _) async {
          calls++;
          throw StateError('registration failed');
        }),
      );
      addTearDown(cloud.dispose);
      cloud.startForConnection('AA:BB:CC:DD:EE:01');
      await Future<void>.delayed(Duration.zero);
      expect(cloud.enabled, false);
      expect(cloud.status, contains('失敗'));
      expect(calls, 1);
    },
  );
  test('invalid IDs and empty audio do not reach the server', () async {
    var calls = 0;
    final service = api((_, _, _) async {
      calls++;
      return null;
    });
    await expectLater(service.registerDevice('bad/id'), throwsFormatException);
    await expectLater(
      service.talkToPet(deviceId: 'a', petId: 'b', pcm: Uint8List(0)),
      throwsFormatException,
    );
    expect(calls, 0);
  });
  test('recordings before confirmation are never uploaded later', () async {
    var calls = 0;
    final cloud = VoiceCloudService(
      api: api((name, data, _) async {
        calls++;
        return registration(data['deviceId'] as String);
      }),
    );
    addTearDown(cloud.dispose);
    cloud.setConnection('AA:BB:CC:DD:EE:01');
    await cloud.sendPcm(Uint8List(10));
    expect(calls, 0);
    await cloud.enable();
    expect(calls, 1);
    expect(cloud.enabled, true);
  });
  test(
    'registration failure leaves upload disabled with function code and reason',
    () async {
      final cloud = VoiceCloudService(
        api: api(
          (_, _, _) async => throw FirebaseFunctionsException(
            code: 'permission-denied',
            message: 'not yours',
            details: {'reason': 'ownership'},
          ),
        ),
      );
      addTearDown(cloud.dispose);
      cloud.setConnection('AA:BB:CC:DD:EE:01');
      await cloud.enable();
      expect(cloud.enabled, false);
      expect(cloud.status, contains('registerDevice'));
      expect(cloud.status, contains('AABBCCDDEE01'));
      expect(cloud.status, contains('permission-denied'));
    },
  );
  test(
    'disconnect while registration is pending never enables another device',
    () async {
      final pending = Completer<Object?>();
      final cloud = VoiceCloudService(api: api((_, _, _) => pending.future));
      addTearDown(cloud.dispose);
      cloud.setConnection('AA:BB:CC:DD:EE:01');
      final registrationFuture = cloud.enable();
      cloud.setConnection('AA:BB:CC:DD:EE:02');
      pending.complete(registration('AABBCCDDEE01'));
      await registrationFuture;
      expect(cloud.enabled, false);
      expect(cloud.busy, false);
    },
  );
  test(
    'only one audio request is active and disconnect discards old results',
    () async {
      var calls = 0;
      final pending = Completer<Object?>();
      final cloud = VoiceCloudService(
        api: api((name, data, _) async {
          if (name == 'registerDevice') {
            return registration(data['deviceId'] as String);
          }
          calls++;
          return pending.future;
        }),
      );
      addTearDown(cloud.dispose);
      cloud.setConnection('AA:BB:CC:DD:EE:01');
      await cloud.enable();
      final first = cloud.sendPcm(Uint8List(10));
      await cloud.sendPcm(Uint8List(10));
      expect(calls, 1);
      cloud.setConnection(null);
      pending.complete(reply());
      await first;
      expect(cloud.enabled, false);
      expect(cloud.replyText, isNull);
    },
  );
  test(
    'pet_changed discards conversation and disables further uploads',
    () async {
      final cloud = VoiceCloudService(
        api: api((name, data, _) async {
          if (name == 'registerDevice') {
            return registration(data['deviceId'] as String);
          }
          throw FirebaseFunctionsException(
            code: 'failed-precondition',
            message: 'changed',
            details: {'reason': 'pet_changed', 'currentPetId': 'pet-2'},
          );
        }),
      );
      addTearDown(cloud.dispose);
      cloud.setConnection('AA:BB:CC:DD:EE:01');
      await cloud.enable();
      await cloud.sendPcm(Uint8List(10));
      expect(cloud.enabled, false);
      expect(cloud.replyText, isNull);
      expect(cloud.status, contains('pet_changed'));
    },
  );
  test(
    'no_speech and synthesis failure are represented without losing valid text',
    () async {
      for (final result in [
        reply(status: 'no_speech'),
        reply(audioStatus: 'failed'),
        reply(audioStatus: 'ok'),
      ]) {
        final cloud = VoiceCloudService(
          api: api(
            (name, data, _) async => name == 'registerDevice'
                ? registration(data['deviceId'] as String)
                : result,
          ),
        );
        cloud.setConnection('AA:BB:CC:DD:EE:01');
        await cloud.enable();
        await cloud.sendPcm(Uint8List(10));
        expect(cloud.enabled, true);
        if (result['status'] == 'no_speech') {
          expect(cloud.status, contains('聞き取れません'));
        } else {
          expect(cloud.replyText, 'やあ');
        }
        if (result['audioStatus'] == 'ok') expect(cloud.replyAudio, isNotEmpty);
        cloud.dispose();
      }
    },
  );
  test('rate limit is shown and no automatic retry occurs', () async {
    var calls = 0;
    final cloud = VoiceCloudService(
      api: api((name, data, _) async {
        if (name == 'registerDevice') {
          return registration(data['deviceId'] as String);
        }
        calls++;
        throw FirebaseFunctionsException(
          code: 'resource-exhausted',
          message: 'wait',
          details: {'reason': 'rate_limited', 'retryAfterSec': 12},
        );
      }),
    );
    addTearDown(cloud.dispose);
    cloud.setConnection('AA:BB:CC:DD:EE:01');
    await cloud.enable();
    await cloud.sendPcm(Uint8List(10));
    expect(calls, 1);
    expect(cloud.status, contains('rate_limited'));
    expect(cloud.status, contains('12秒後'));
  });
}
