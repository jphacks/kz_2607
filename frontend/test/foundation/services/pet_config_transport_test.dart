import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/services/pet_config_transport.dart';

List<int> responseFrame(List<int> request, int type, int sequence,
    int count, List<int> payload) {
  final frame = List<int>.filled(20, 0);
  frame[0] = 70;
  frame[1] = 1;
  frame[2] = type;
  frame.setRange(4, 12, request.sublist(4, 12));
  frame[12] = sequence;
  frame[13] = count;
  frame[14] = payload.length;
  frame.setRange(15, 15 + payload.length, payload);
  return frame;
}

void main() {
  test('unsolicited exchange candidate is reassembled and acknowledged', () async {
    final acks = <List<int>>[];
    final messages = <Map<String, dynamic>>[];
    final transport = PetConfigTransport((bytes) async { acks.add(bytes); });
    transport.onMessage = messages.add;
    const tx = '0123456789ABCDEF';
    final payload = utf8.encode(jsonEncode({
      'type': 'exchange_pending',
      'transactionId': tx,
      'myDeviceId': 'AABBCCDDEEFF',
      'peerDeviceId': '112233445566',
      'givenPetId': 'pet-a',
      'gotPetId': 'pet-b',
      'distanceMeters': 0.1,
    }));
    final count = (payload.length + 4) ~/ 5;
    for (var i = 0; i < count; i++) {
      final start = i * 5;
      expect(transport.receive(PetConfigTransport.frame(tx, 1, i, count,
          payload.sublist(start, start + 5 < payload.length
              ? start + 5 : payload.length))), isTrue);
    }
    await Future<void>.delayed(Duration.zero);
    expect(messages, hasLength(1));
    expect(messages.single['distanceMeters'], 0.1);
    expect(acks, hasLength(count));
    transport.close();
  });

  test('petId is sent to the selected Core2 and confirmed by its ACK', () async {
    const deviceId = 'AABBCCDDEEFF';
    const petId = 'pet-123';
    late PetConfigTransport transport;
    final payload = <int>[];
    var receivedFrames = 0;

    transport = PetConfigTransport((bytes) async {
      expect(bytes.length, 20);
      if (bytes[2] != 1) return; // ACK for the Core2 application response.
      receivedFrames++;
      payload.addAll(bytes.sublist(15, 15 + bytes[14]));
      transport.receive(responseFrame(bytes, 2, bytes[12], 0, const []));
      if (bytes[12] != bytes[13] - 1) return;

      final request = jsonDecode(utf8.decode(payload)) as Map<String, dynamic>;
      expect(request['type'], 'pet_config');
      expect(request['deviceId'], deviceId);
      expect(request['petId'], petId);
      final ack = utf8.encode(jsonEncode({
        'type': 'pet_config_ack',
        'transactionId': request['transactionId'],
        'status': 'received',
        'deviceId': deviceId,
      }));
      final count = (ack.length + 4) ~/ 5;
      for (var i = 0; i < count; i++) {
        final start = i * 5;
        transport.receive(responseFrame(bytes, 1, i, count,
            ack.sublist(start, start + 5 < ack.length ? start + 5 : ack.length)));
      }
    });

    await transport.sendConfig(deviceId: deviceId, petId: petId);
    expect(receivedFrames, greaterThan(1));
    transport.close();
  });
}
