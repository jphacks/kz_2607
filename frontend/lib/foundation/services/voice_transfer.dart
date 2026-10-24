import 'dart:typed_data';

/// Transport-independent parser for the reference Core2 voice protocol.
class VoiceTransfer {
  VoiceTransfer({
    required this.chunkSize,
    required this.ack,
    required this.onAudio,
    required this.onProgress,
  });
  final int chunkSize;
  final void Function(int session, int sequence) ack;
  final void Function(Uint8List pcm) onAudio;
  final void Function(int received, int expected) onProgress;
  Uint8List? _buffer;
  int _session = -1, _count = 0, _codec = 0, _next = 1, _received = 0;
  int _completedSession = -1, _completedEnd = -1;
  bool get active => _buffer != null;
  void reset() {
    _buffer = null;
    _session = -1;
  }

  void receive(List<int> packet) {
    if (packet.length < 4) throw const FormatException('音声パケットが短すぎます');
    final type = packet[0], session = packet[1];
    final sequence = packet[2] | packet[3] << 8;
    if (type == 1) {
      if (packet.length != 6 && packet.length != 7) {
        throw const FormatException('STARTの長さが不正です');
      }
      final count = sequence | packet[4] << 16 | packet[5] << 24;
      final codec = packet.length == 7 ? packet[6] : 0;
      if (count < 3200 || count > 80000 || (codec != 0 && codec != 1)) {
        throw const FormatException('音声サイズまたはコーデックが未対応です');
      }
      if (_buffer != null && _session == session) {
        if (count != _count || codec != _codec) {
          throw const FormatException('同一セッションのSTART内容が変わりました');
        }
        ack(session, 0);
        return;
      }
      _session = session;
      _count = count;
      _codec = codec;
      _buffer = Uint8List(codec == 1 ? (count + 1) ~/ 2 : count);
      _next = 1;
      _received = 0;
      _completedSession = -1;
      _completedEnd = -1;
      onProgress(0, _buffer!.length);
      ack(session, 0);
      return;
    }
    if (type == 3 &&
        packet.length == 4 &&
        session == _completedSession &&
        sequence == _completedEnd) {
      ack(session, sequence);
      return;
    }
    if (_buffer == null || session != _session) return;
    if (type == 2) {
      if (sequence < 1) throw const FormatException('DATAの連番が不正です');
      final offset = (sequence - 1) * chunkSize;
      final length = (_buffer!.length - offset).clamp(0, chunkSize);
      if (length == 0 || packet.length != length + 4) {
        throw const FormatException('DATAのサイズが不正です');
      }
      if (sequence == _next) {
        _buffer!.setRange(_received, _received + length, packet, 4);
        _received += length;
        _next++;
        onProgress(_received, _buffer!.length);
        if (sequence % 4 == 0 || _received == _buffer!.length) {
          ack(session, sequence);
        }
      } else if (sequence < _next &&
          ((_next - 1) % 4 == 0 || _received == _buffer!.length)) {
        ack(session, _next - 1);
      }
      // Future frames are ignored. Sender retries the unacknowledged window.
    } else if (type == 3) {
      if (packet.length != 4 ||
          sequence != _next ||
          _received != _buffer!.length) {
        throw const FormatException('音声が揃う前にENDを受信しました');
      }
      final pcm = decodeVoice(_buffer!, _count, _codec);
      _buffer = null;
      _completedSession = session;
      _completedEnd = sequence;
      ack(session, sequence);
      onAudio(pcm);
    } else {
      throw const FormatException('未対応の音声パケットです');
    }
  }
}

Uint8List decodeVoice(Uint8List input, int count, int codec) {
  final output = Uint8List(count * 2);
  final view = ByteData.sublistView(output);
  var predictor = 0, index = 0;
  for (var i = 0; i < count; i++) {
    if (codec == 0) {
      final sample = input[i] < 128 ? input[i] : input[i] - 256;
      view.setInt16(i * 2, sample << 8, Endian.little);
    } else {
      final nibble = i.isEven ? input[i ~/ 2] & 15 : input[i ~/ 2] >> 4;
      final step = _steps[index];
      var delta = step >> 3;
      if (nibble & 4 != 0) delta += step;
      if (nibble & 2 != 0) delta += step >> 1;
      if (nibble & 1 != 0) delta += step >> 2;
      predictor = (predictor + (nibble & 8 != 0 ? -delta : delta)).clamp(
        -32768,
        32767,
      );
      index = (index + _indices[nibble & 7]).clamp(0, 88);
      view.setInt16(i * 2, predictor, Endian.little);
    }
  }
  return output;
}

const _indices = [-1, -1, -1, -1, 2, 4, 6, 8];
const _steps = [
  7,
  8,
  9,
  10,
  11,
  12,
  13,
  14,
  16,
  17,
  19,
  21,
  23,
  25,
  28,
  31,
  34,
  37,
  41,
  45,
  50,
  55,
  60,
  66,
  73,
  80,
  88,
  97,
  107,
  118,
  130,
  143,
  157,
  173,
  190,
  209,
  230,
  253,
  279,
  307,
  337,
  371,
  408,
  449,
  494,
  544,
  598,
  658,
  724,
  796,
  876,
  963,
  1060,
  1166,
  1282,
  1411,
  1552,
  1707,
  1878,
  2066,
  2272,
  2499,
  2749,
  3024,
  3327,
  3660,
  4026,
  4428,
  4871,
  5358,
  5894,
  6484,
  7132,
  7845,
  8630,
  9493,
  10442,
  11487,
  12635,
  13899,
  15289,
  16818,
  18500,
  20350,
  22385,
  24623,
  27086,
  29794,
  32767,
];

/// PCM16 little endian, mono, 16 kHz.
Uint8List voiceWav(Uint8List pcm) {
  if (pcm.isEmpty || pcm.length.isOdd || pcm.length > 160000) {
    throw const FormatException('PCMサイズが不正です');
  }
  final wav = Uint8List(44 + pcm.length);
  final header = ByteData.sublistView(wav);
  void tag(int at, String text) =>
      wav.setRange(at, at + text.length, text.codeUnits);
  tag(0, 'RIFF');
  tag(8, 'WAVE');
  tag(12, 'fmt ');
  tag(36, 'data');
  header.setUint32(4, pcm.length + 36, Endian.little);
  header.setUint32(16, 16, Endian.little);
  header.setUint16(20, 1, Endian.little);
  header.setUint16(22, 1, Endian.little);
  header.setUint32(24, 16000, Endian.little);
  header.setUint32(28, 32000, Endian.little);
  header.setUint16(32, 2, Endian.little);
  header.setUint16(34, 16, Endian.little);
  header.setUint32(40, pcm.length, Endian.little);
  wav.setRange(44, wav.length, pcm);
  return wav;
}
