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
      final audio = Uint8List.fromList(List.generate(70, (i) => i));
      final sender = ReplyVoiceSender(
        acknowledgements: ack.stream,
        write: (p, fast) async {
          frames.add(List.of(p));
          if (p[0] == 1) {
            expect(fast, false);
            expect(p.sublist(2), [140, 0, 0, 0, 1, 16]);
            ack.add([2, p[1], 0, 0]);
          }
          if (p[0] == 2) {
            expect(fast, true);
            if (p[2] == 4 || p[2] == 5) ack.add([2, p[1], p[2], p[3]]);
          }
          if (p[0] == 3) {
            expect(fast, false);
            ack.add([2, p[1], 6, 0]);
          }
        },
      );
      await sender.send(
        bytes: audio,
        sampleCount: 140,
        chunkSize: 16,
        onProgress: (sent, _) => progress.add(sent),
      );
      expect(frames.first[0], 1);
      expect(frames.last, [3, 1, 6, 0]);
      expect(
        frames.where((p) => p[0] == 2).expand((p) => p.skip(4)).toList(),
        audio,
      );
      expect(progress, [0, 64, 70]);
      await sender.close();
      await ack.close();
    },
  );
  test('lost cumulative DATA and END ACKs resend identical packets', () async {
    final ack = StreamController<List<int>>(sync: true);
    var windowEnds = 0, ends = 0;
    final sender = ReplyVoiceSender(
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
    await sender.close();
    await ack.close();
  });
  test('future ACK and another session cannot confirm unsent data', () async {
    final ack = StreamController<List<int>>(sync: true);
    var dataFrames = 0;
    final sender = ReplyVoiceSender(
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
