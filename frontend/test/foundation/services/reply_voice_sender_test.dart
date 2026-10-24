import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/services/reply_voice_sender.dart';

void main() {
  test(
    'START DATA END use the reference wire format and require END ACK',
    () async {
      final ack = StreamController<List<int>>(sync: true);
      final frames = <List<int>>[];
      final progress = <int>[];
      final metrics = <Map<String, Object?>>[];
      final audio = Uint8List.fromList(List.generate(144, (i) => i));
      final sender = ReplyVoiceSender(
        onMetrics: metrics.add,
        acknowledgements: ack.stream,
        write: (p, fast) async {
          frames.add(List.of(p));
          if (p[0] == 1) {
            expect(fast, false);
            expect(p.sublist(2), [32, 1, 0, 0, 1, 16]);
            ack.add([2, p[1], 0, 0]);
          }
          if (p[0] == 2) {
            expect(fast, true);
            if (p[2] == 4 || p[2] == 8 || p[2] == 9) {
              ack.add([2, p[1], p[2], p[3]]);
            }
          }
          if (p[0] == 3) {
            expect(fast, false);
            ack.add([2, p[1], 10, 0]);
          }
        },
      );
      await sender.send(
        bytes: audio,
        sampleCount: 288,
        chunkSize: 16,
        cloudToSendUs: 1000,
        onProgress: (sent, _) => progress.add(sent),
      );
      expect(frames.first[0], 1);
      expect(frames.last, [3, 1, 10, 0]);
      expect(
        frames.where((p) => p[0] == 2).expand((p) => p.skip(4)).toList(),
        audio,
      );
      expect(progress.first, 0);
      expect(progress.last, 144);
      final result = metrics.single;
      expect(result['success'], true);
      expect(result['resentPackets'], 0);
      expect(
        result['totalUs'],
        greaterThanOrEqualTo(
          (result['cloudToStartAckUs'] as int) +
              (result['dataUs'] as int) +
              (result['endAckUs'] as int),
        ),
      );
      expect(result['totalUs'], (result['transferUs'] as int) + 1000);
      await sender.close();
      await ack.close();
    },
  );
  test('lost cumulative DATA and END ACKs resend identical packets', () async {
    final ack = StreamController<List<int>>(sync: true);
    var windowEnds = 0, ends = 0;
    final metrics = <Map<String, Object?>>[];
    final sender = ReplyVoiceSender(
      onMetrics: metrics.add,
      acknowledgements: ack.stream,
      ackTimeout: const Duration(milliseconds: 5),
      attempts: 3,
      write: (p, _) async {
        if (p[0] == 1) ack.add([2, p[1], 0, 0]);
        if (p[0] == 2 && p[2] == 4 && ++windowEnds > 1) {
          ack.add([2, p[1], 4, 0]);
        }
        if (p[0] == 3 && ++ends > 1) ack.add([2, p[1], 5, 0]);
      },
    );
    await sender.send(bytes: Uint8List(64), sampleCount: 128, chunkSize: 16);
    expect(windowEnds, 2);
    expect(ends, 2);
    expect(sender.retryCount, 2);
    expect(metrics.single['success'], true);
    expect(metrics.single['ackWindow'], 8);
    expect(metrics.single['packets'], 4);
    expect(metrics.single['dataWrites'], 8);
    expect(metrics.single['resentPackets'], 4);
    expect(metrics.single['retransmitRate'], .5);
    expect(metrics.single['ackTimeouts'], 2);
    expect(metrics.single['retries'], 2);
    expect(metrics.single['ackWaitUs'], greaterThan(0));
    expect(metrics.single['endAckUs'], isA<int>());
    await sender.close();
    await ack.close();
  });
  test('future ACK and another session cannot confirm unsent data', () async {
    final ack = StreamController<List<int>>(sync: true);
    var dataFrames = 0;
    final metrics = <Map<String, Object?>>[];
    final sender = ReplyVoiceSender(
      onMetrics: metrics.add,
      acknowledgements: ack.stream,
      ackTimeout: const Duration(milliseconds: 5),
      attempts: 2,
      write: (p, _) async {
        if (p[0] == 1) {
          ack.add([2, p[1], 255, 255]);
          ack.add([2, (p[1] + 1) & 255, 0, 0]);
        }
        if (p[0] == 2) dataFrames++;
      },
    );
    await expectLater(
      sender.send(bytes: Uint8List(8), sampleCount: 16, chunkSize: 16),
      throwsStateError,
    );
    expect(dataFrames, 0);
    expect(metrics.single['success'], false);
    expect(metrics.single['cloudToStartAckUs'], isNull);
    expect(metrics.single['dataUs'], isNull);
    expect(metrics.single['endAckUs'], isNull);
    await sender.close();
    await ack.close();
  });
  test(
    'Core2 busy error is reported rather than accepted as successful',
    () async {
      final ack = StreamController<List<int>>(sync: true);
      final sender = ReplyVoiceSender(
        acknowledgements: ack.stream,
        write: (p, _) async {
          ack.add([4, p[1], 2, 0]);
        },
      );
      await expectLater(
        sender.send(bytes: Uint8List(8), sampleCount: 16, chunkSize: 16),
        throwsA(
          isA<StateError>().having(
            (e) => e.message,
            'message',
            contains('録音・再生中'),
          ),
        ),
      );
      await sender.close();
      await ack.close();
    },
  );
  test('disconnect wakes an ACK wait immediately', () async {
    final ack = StreamController<List<int>>(sync: true);
    final wrote = Completer<void>();
    final sender = ReplyVoiceSender(
      acknowledgements: ack.stream,
      write: (p, _) async {
        wrote.complete();
      },
    );
    final request = sender.send(
      bytes: Uint8List(8),
      sampleCount: 16,
      chunkSize: 16,
    );
    final expectation = expectLater(request, throwsStateError);
    await wrote.future;
    await sender.close();
    await expectation;
    await ack.close();
  });
  test(
    'invalid audio is never written and concurrent sends are rejected',
    () async {
      final ack = StreamController<List<int>>(sync: true);
      var writes = 0;
      final sender = ReplyVoiceSender(
        acknowledgements: ack.stream,
        write: (p, _) async {
          writes++;
        },
      );
      await expectLater(
        sender.send(bytes: Uint8List(8), sampleCount: 100, chunkSize: 16),
        throwsFormatException,
      );
      expect(writes, 0);
      final pending = sender.send(
        bytes: Uint8List(8),
        sampleCount: 16,
        chunkSize: 16,
      );
      final expectation = expectLater(pending, throwsStateError);
      await expectLater(
        sender.send(bytes: Uint8List(8), sampleCount: 16, chunkSize: 16),
        throwsStateError,
      );
      await sender.close();
      await expectation;
      await ack.close();
    },
  );
}
