import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/services/pet_image_sender.dart';

Uint8List imageBytes(int length) {
  final bytes = Uint8List.fromList(List.generate(length, (i) => i & 255));
  bytes.setRange(0, 8, [137, 80, 78, 71, 13, 10, 26, 10]);
  return bytes;
}

void main() {
  test('CRC32 agrees with the standard check value', () {
    expect(PetImageSender.crc32(Uint8List.fromList('123456789'.codeUnits)),
        0xcbf43926);
  });

  test('sends PNG metadata, ordered chunks, and waits for final ACK', () async {
    final ack = StreamController<List<int>>(sync: true);
    final frames = <List<int>>[];
    final metrics = <Map<String, Object?>>[];
    final bytes = imageBytes(50);
    final sender = PetImageSender(
      acknowledgements: ack.stream,
      onMetrics: metrics.add,
      write: (packet, fast) async {
        frames.add(List.of(packet));
        if (packet[0] == 1) {
          expect(fast, false);
          expect(packet.length, 20);
          expect(packet.sublist(2, 8), [192, 0, 192, 0, 1, 16]);
          expect(packet.sublist(8, 12), [50, 0, 0, 0]);
          final crc = packet[12] | packet[13] << 8 |
              packet[14] << 16 | packet[15] << 24;
          expect(crc, PetImageSender.crc32(bytes));
          final petCrc = packet[16] | packet[17] << 8 |
              packet[18] << 16 | packet[19] << 24;
          expect(petCrc,
              PetImageSender.crc32(Uint8List.fromList('pet-A'.codeUnits)));
          ack.add([2, packet[1], 0, 0]);
        } else if (packet[0] == 2 && packet[2] == 4) {
          expect(fast, true);
          ack.add([2, packet[1], 4, 0]);
        } else if (packet[0] == 3) {
          expect(fast, false);
          ack.add([2, packet[1], 5, 0]);
        }
      },
    );
    final progress = <int>[];
    await sender.send(
      png: bytes,
      petId: 'pet-A',
      width: 192,
      height: 192,
      chunkSize: 16,
      onProgress: (sent, _, __) => progress.add(sent),
    );
    expect(frames.where((p) => p[0] == 2).expand((p) => p.skip(4)).toList(), bytes);
    expect(progress, [0, 50]);
    expect(metrics.single['success'], true);
    expect(metrics.single['imageBytes'], 50);
    expect(metrics.single['packets'], 4);
    expect(metrics.single['transferUs'], isA<int>());
    await sender.close();
    await ack.close();
  });

  test('lost DATA and END acknowledgements retry the same window', () async {
    final ack = StreamController<List<int>>(sync: true);
    var lastDataWrites = 0, endWrites = 0;
    final metrics = <Map<String, Object?>>[];
    final sender = PetImageSender(
      acknowledgements: ack.stream,
      onMetrics: metrics.add,
      ackTimeout: const Duration(milliseconds: 5),
      attempts: 3,
      write: (packet, _) async {
        if (packet[0] == 1) ack.add([2, packet[1], 0, 0]);
        if (packet[0] == 2 && packet[2] == 4 && ++lastDataWrites == 2) {
          ack.add([2, packet[1], 4, 0]);
        }
        if (packet[0] == 3 && ++endWrites == 2) {
          ack.add([2, packet[1], 5, 0]);
        }
      },
    );
    await sender.send(png: imageBytes(50), petId: 'pet-A', width: 192,
        height: 192, chunkSize: 16);
    expect(lastDataWrites, 2);
    expect(endWrites, 2);
    expect(metrics.single['dataWrites'], 8);
    expect(metrics.single['retries'], 1);
    await sender.close();
    await ack.close();
  });

  test('a future ACK cannot complete unsent image data', () async {
    final ack = StreamController<List<int>>(sync: true);
    var sentData = false;
    final sender = PetImageSender(
      acknowledgements: ack.stream,
      ackTimeout: const Duration(milliseconds: 5),
      attempts: 2,
      write: (packet, _) async {
        if (packet[0] == 1) ack.add([2, packet[1], 255, 255]);
        if (packet[0] == 2) sentData = true;
      },
    );
    await expectLater(sender.send(png: imageBytes(20), petId: 'pet-A', width: 20,
        height: 20, chunkSize: 16), throwsStateError);
    expect(sentData, false);
    await sender.close();
    await ack.close();
  });

  test('receiver error aborts the transfer', () async {
    final ack = StreamController<List<int>>(sync: true);
    final sender = PetImageSender(
      acknowledgements: ack.stream,
      write: (packet, _) async => ack.add([4, packet[1], 4, 0]),
    );
    await expectLater(sender.send(png: imageBytes(20), petId: 'pet-A', width: 20,
        height: 20, chunkSize: 16), throwsStateError);
    await sender.close();
    await ack.close();
  });
}
