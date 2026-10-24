#include "reply_receiver.h"

#include <Arduino.h>
#include <M5Unified.h>
#include <esp_heap_caps.h>
#include <string.h>

#include "voice_recorder.h"
#include "voice_transfer.h"

namespace {

constexpr char kReplyDataUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000007";
constexpr char kReplyAckUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000008";
constexpr uint32_t kMaxSamples = 16000UL * 30;
constexpr unsigned long kReceiveTimeoutMs = 8000;
constexpr size_t kQueueCapacity = 16;
constexpr size_t kMaxPacketSize = 244;
constexpr size_t kPlaybackChunkSamples = 8000;  // 500 ms at 16 kHz.
constexpr size_t kMinPrebufferSamples = 16000;   // At least one second.
constexpr uint32_t kPrebufferSafetyMs = 400;

struct QueuedPacket {
  uint8_t bytes[kMaxPacketSize];
  uint16_t length;
};

QueuedPacket queue[kQueueCapacity];
size_t queueHead = 0;
size_t queueCount = 0;
portMUX_TYPE queueMux = portMUX_INITIALIZER_UNLOCKED;
NimBLECharacteristic* ackCharacteristic = nullptr;

enum class State { Idle, Receiving, Ready, Playing };
State state = State::Idle;
int16_t* pcm = nullptr;
uint8_t session = 0;
uint8_t chunkSize = 0;
uint32_t sampleCount = 0;
size_t encodedSize = 0;
size_t received = 0;
size_t decodedSamples = 0;
size_t queuedSamples = 0;
int predictor = 0;
int index = 0;
bool playbackStarted = false;
bool playbackQueueEmpty = false;
uint16_t playbackUnderruns = 0;
uint16_t expectedSequence = 1;
uint8_t completedSession = 0;
uint16_t completedEnd = 0;
bool hasCompleted = false;
unsigned long lastPacketAt = 0;
unsigned long transferStartedAt = 0;
uint32_t revision = 0;

class ReplyDataCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
    const std::string value = characteristic->getValue();
    if (value.empty() || value.size() > kMaxPacketSize) return;
    portENTER_CRITICAL(&queueMux);
    if (queueCount < kQueueCapacity) {
      QueuedPacket& slot = queue[(queueHead + queueCount) % kQueueCapacity];
      slot.length = value.size();
      memcpy(slot.bytes, value.data(), value.size());
      ++queueCount;
    }
    portEXIT_CRITICAL(&queueMux);
  }
};

bool popPacket(QueuedPacket& out) {
  portENTER_CRITICAL(&queueMux);
  const bool available = queueCount != 0;
  if (available) {
    out = queue[queueHead];
    queueHead = (queueHead + 1) % kQueueCapacity;
    --queueCount;
  }
  portEXIT_CRITICAL(&queueMux);
  return available;
}

void sendAck(uint8_t currentSession, uint16_t sequence) {
  const uint8_t packet[] = {2, currentSession,
                            static_cast<uint8_t>(sequence),
                            static_cast<uint8_t>(sequence >> 8)};
  ackCharacteristic->notify(packet, sizeof(packet));
}

void sendError(uint8_t currentSession, uint8_t code) {
  const uint8_t packet[] = {4, currentSession, code, 0};
  ackCharacteristic->notify(packet, sizeof(packet));
}

void releaseAudio() {
  if (playbackStarted) {
    Serial.printf("Voice downlink: playback buffer underruns %u\n",
                  playbackUnderruns);
  }
  // playRaw keeps pointers into pcm until the speaker stops.
  if (voicePlayingReply()) voiceCancel("Reply stopped");
  if (pcm != nullptr) heap_caps_free(pcm);
  pcm = nullptr;
  state = State::Idle;
  received = 0;
  decodedSamples = 0;
  queuedSamples = 0;
  playbackStarted = false;
  playbackQueueEmpty = false;
  playbackUnderruns = 0;
  ++revision;
}

void decodePacket(const uint8_t* data, size_t length) {
  static constexpr int step[89] = {
      7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
      34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
      143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
      494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
      1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660,
      4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
      11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
      27086, 29794, 32767};
  static constexpr int indexChange[8] = {-1, -1, -1, -1, 2, 4, 6, 8};
  for (size_t byte = 0; byte < length && decodedSamples < sampleCount; ++byte) {
    for (int half = 0; half < 2 && decodedSamples < sampleCount; ++half) {
      const uint8_t code = half ? data[byte] >> 4 : data[byte] & 15;
      const int currentStep = step[index];
      int change = currentStep >> 3;
      if (code & 4) change += currentStep;
      if (code & 2) change += currentStep >> 1;
      if (code & 1) change += currentStep >> 2;
      predictor = constrain(predictor + ((code & 8) ? -change : change),
                            -32768, 32767);
      index = constrain(index + indexChange[code & 7], 0, 88);
      pcm[decodedSamples++] = predictor;
    }
  }
}

void handlePacket(const QueuedPacket& incoming) {
  const uint8_t* packet = incoming.bytes;
  const size_t length = incoming.length;
  if (length < 2) return;
  const uint8_t incomingSession = packet[1];

  if (packet[0] == 1) {
    if (length != 8) {
      sendError(incomingSession, 1);
      return;
    }
    const uint32_t count = static_cast<uint32_t>(packet[2]) |
                           (static_cast<uint32_t>(packet[3]) << 8) |
                           (static_cast<uint32_t>(packet[4]) << 16) |
                           (static_cast<uint32_t>(packet[5]) << 24);
    const uint8_t chunk = packet[7];
    const uint32_t bytes = (count + 1) / 2;
    const uint32_t packets = chunk == 0 ? UINT32_MAX : (bytes + chunk - 1) / chunk;
    if (packet[6] != 1 || count == 0 || count > kMaxSamples ||
        chunk == 0 || chunk > 240 || packets >= UINT16_MAX) {
      sendError(incomingSession, 1);
      return;
    }
    if (state == State::Receiving && incomingSession == session &&
        count == sampleCount && chunk == chunkSize) {
      sendAck(incomingSession, 0);  // START ACK may have been lost.
      return;
    }
    if (state != State::Idle || voiceRecording() || voiceReady() ||
        voiceTransferSending() || !voiceCanPlayReply()) {
      sendError(incomingSession, 2);
      return;
    }
    pcm = static_cast<int16_t*>(heap_caps_malloc(
        count * sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (pcm == nullptr) {
      sendError(incomingSession, 3);
      return;
    }
    session = incomingSession;
    sampleCount = count;
    chunkSize = chunk;
    encodedSize = bytes;
    received = 0;
    decodedSamples = 0;
    queuedSamples = 0;
    predictor = 0;
    index = 0;
    playbackStarted = false;
    playbackQueueEmpty = false;
    playbackUnderruns = 0;
    expectedSequence = 1;
    hasCompleted = false;
    lastPacketAt = millis();
    transferStartedAt = lastPacketAt;
    state = State::Receiving;
    ++revision;
    sendAck(session, 0);
    return;
  }

  if (length != 4 && packet[0] == 3) return;
  if (packet[0] == 3 && hasCompleted &&
      incomingSession == completedSession &&
      (packet[2] | (static_cast<uint16_t>(packet[3]) << 8)) == completedEnd) {
    sendAck(completedSession, completedEnd);  // END ACK may have been lost.
    return;
  }
  if (state != State::Receiving || incomingSession != session || length < 4) return;
  const uint16_t sequence = packet[2] |
                            (static_cast<uint16_t>(packet[3]) << 8);
  if (packet[0] == 2) {
    if (sequence == 0) return;
    const size_t offset = static_cast<size_t>(sequence - 1) * chunkSize;
    if (offset >= encodedSize) return;
    const size_t expectedLength = min(static_cast<size_t>(chunkSize),
                                      encodedSize - offset);
    if (length != expectedLength + 4) return;
    if (sequence == expectedSequence && offset == received) {
      decodePacket(packet + 4, expectedLength);
      received += expectedLength;
      ++expectedSequence;
      lastPacketAt = millis();
      if (sequence % 4 == 0 || received == encodedSize) {
        ++revision;
        sendAck(session, sequence);
      }
    } else if (sequence < expectedSequence && (sequence - 1) % 4 == 0 &&
               ((expectedSequence - 1) % 4 == 0 || received == encodedSize)) {
      sendAck(session, expectedSequence - 1);
    }
  } else if (packet[0] == 3 && sequence == expectedSequence &&
             received == encodedSize && decodedSamples == sampleCount) {
    hasCompleted = true;
    completedSession = session;
    completedEnd = sequence;
    state = State::Ready;
    ++revision;
    Serial.printf("Voice downlink: received %u bytes in %lu ms\n",
                  static_cast<unsigned>(received), millis() - transferStartedAt);
    sendAck(session, sequence);
  }
}

void queuePlayback() {
  if (state != State::Receiving && state != State::Ready &&
      state != State::Playing) return;
  const bool wholeReply = state == State::Ready && !playbackStarted;
  if (!playbackStarted) {
    if (state != State::Ready) {
      if (decodedSamples == 0) return;
      const uint32_t elapsedMs = millis() - transferStartedAt;
      const uint32_t audioMs = sampleCount / 16;
      const uint32_t estimatedTransferMs =
          static_cast<uint64_t>(elapsedMs) * sampleCount / decodedSamples;
      const uint32_t targetMs = estimatedTransferMs > audioMs
          ? estimatedTransferMs - audioMs + kPrebufferSafetyMs
          : kMinPrebufferSamples / 16;
      const size_t targetSamples = targetMs >= audioMs
          ? sampleCount
          : min(static_cast<size_t>(sampleCount),
                max(kMinPrebufferSamples, static_cast<size_t>(targetMs) * 16));
      // A link this slow cannot sustain streaming. Wait for END and play the
      // contiguous PCM buffer to avoid repeated speaker queue boundaries.
      if (targetSamples >= static_cast<size_t>(sampleCount) * 3 / 4) return;
      if (decodedSamples < targetSamples) return;
    }
    if (!voiceStartReplyStream()) {
      voiceCancel("Reply playback failed");
      releaseAudio();
      return;
    }
    playbackStarted = true;
    if (state == State::Ready) state = State::Playing;
    ++revision;
  }
  while (queuedSamples < decodedSamples) {
    const size_t available = decodedSamples - queuedSamples;
    if (available < kPlaybackChunkSamples && state != State::Ready &&
        state != State::Playing) break;
    const size_t count = wholeReply ? available
                                    : min(available, kPlaybackChunkSamples);
    if (M5.Speaker.isPlaying(0) >= 2) break;
    if (!voiceQueueReplySamples(pcm + queuedSamples, count)) {
      voiceCancel("Reply playback failed");
      releaseAudio();
      return;
    }
    queuedSamples += count;
    if (queuedSamples == count) {
      Serial.printf("Voice downlink: first chunk queued after %lu ms\n",
                    millis() - transferStartedAt);
    }
  }
  if (state == State::Ready) state = State::Playing;
  if (state == State::Playing && queuedSamples == sampleCount) {
    voiceFinishReplyStream();
  }
  const bool empty = M5.Speaker.isPlaying(0) == 0;
  if (queuedSamples < sampleCount && empty && !playbackQueueEmpty) {
    ++playbackUnderruns;
  }
  playbackQueueEmpty = empty;
}

}  // namespace

void replyReceiverBegin(NimBLEService* service) {
  NimBLECharacteristic* data = service->createCharacteristic(
      kReplyDataUuid, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  data->setCallbacks(new ReplyDataCallbacks());
  ackCharacteristic = service->createCharacteristic(
      kReplyAckUuid, NIMBLE_PROPERTY::NOTIFY);
}

void replyReceiverReset() {
  portENTER_CRITICAL(&queueMux);
  queueHead = 0;
  queueCount = 0;
  portEXIT_CRITICAL(&queueMux);
  releaseAudio();
  hasCompleted = false;
}

void replyReceiverUpdate(bool connected) {
  if (!connected) return;
  if (state == State::Receiving && millis() - lastPacketAt > kReceiveTimeoutMs) {
    releaseAudio();
    voiceCancel("Reply receive timeout");
  }
  QueuedPacket packet;
  while (popPacket(packet)) handlePacket(packet);
  queuePlayback();
  if (state == State::Playing && !voicePlayingReply()) releaseAudio();
}

bool replyReceiverBusy() { return state != State::Idle; }
bool replyReceiverReceiving() { return state == State::Receiving; }
uint32_t replyReceiverRevision() { return revision; }
unsigned replyReceiverProgressPercent() {
  return encodedSize == 0 ? 0 : static_cast<unsigned>(100 * received / encodedSize);
}
