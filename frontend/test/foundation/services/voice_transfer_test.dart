import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/services/voice_transfer.dart';

void main() {
  late VoiceTransfer transfer;
  late List<List<int>> acks;
  late List<Uint8List> audio;
  setUp(() {
    acks = [];
    audio = [];
    transfer = VoiceTransfer(
      chunkSize: 240,
      ack: (session, sequence) => acks.add([session, sequence]),
      onAudio: audio.add,
      onProgress: (_, _) {},
    );
  });
  void start({int codec = 0}) =>
      transfer.receive([1, 7, 0x80, 0x0c, 0, 0, codec]);
  void send({int codec = 0, int? skip, bool duplicate = false}) {
    final size = codec == 1 ? 1600 : 3200;
    var sequence = 1;
    for (var offset = 0; offset < size; offset += 240) {
      final length = (size - offset).clamp(0, 240);
      final packet = [
        2,
        7,
        sequence & 255,
        sequence >> 8,
        ...List.filled(length, 0),
      ];
      if (sequence != skip) {
        transfer.receive(packet);
        if (duplicate) transfer.receive(packet);
      }
      sequence++;
    }
    transfer.receive([3, 7, sequence & 255, sequence >> 8]);
  }

  test('complete signed PCM8 transfer produces 16-bit WAV and ACKs', () {
    start();
    send();
    expect(audio.single.length, 6400);
    expect(acks.first, [7, 0]);
    expect(acks.last, [7, 15]);
    final wav = voiceWav(audio.single);
    expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
    final header = ByteData.sublistView(wav);
    expect(header.getUint32(24, Endian.little), 16000);
    expect(header.getUint32(40, Endian.little), 6400);
    expect(wav.length, 6444);
  });
  test('replayed DATA and END do not duplicate audio', () {
    start();
    send(duplicate: true);
    transfer.receive([3, 7, 15, 0]);
    expect(audio.length, 1);
    expect(acks.last, [7, 15]);
  });
  test('missing packet prevents completion', () {
    start();
    expect(() => send(skip: 2), throwsFormatException);
    expect(audio, isEmpty);
  });
  test('window retry fills a gap and ignores packets from another session', () {
    start();
    transfer.receive([2, 8, 1, 0, ...List.filled(240, 0)]);
    transfer.receive([2, 7, 2, 0, ...List.filled(240, 0)]);
    send();
    expect(audio.length, 1);
  });
  test('invalid lengths and oversized recording are rejected', () {
    expect(() => transfer.receive([1, 7, 1]), throwsFormatException);
    expect(
      () => transfer.receive([1, 7, 255, 255, 255, 255, 1]),
      throwsFormatException,
    );
    start();
    expect(() => transfer.receive([2, 7, 1, 0, 0]), throwsFormatException);
  });
  test('ADPCM decoded using predictor zero and low nibble first', () {
    final result = decodeVoice(Uint8List.fromList([0x71]), 2, 1);
    final view = ByteData.sublistView(result);
    expect(view.getInt16(0, Endian.little), 1);
    expect(view.getInt16(2, Endian.little), 12);
    start(codec: 1);
    send(codec: 1);
    expect(audio.single.length, 6400);
  });
  test('reset discards interrupted recording and allows a new transfer', () {
    start();
    transfer.reset();
    transfer.receive([3, 7, 1, 0]);
    expect(audio, isEmpty);
    start();
    send();
    expect(audio.length, 1);
  });
  test('duplicate START preserves collected data; new session replaces it', () {
    start();
    transfer.receive([2, 7, 1, 0, ...List.filled(240, 1)]);
    start();
    send();
    expect(audio.length, 1);
    expect(ByteData.sublistView(audio.single).getInt16(0, Endian.little), 256);
  });
}
