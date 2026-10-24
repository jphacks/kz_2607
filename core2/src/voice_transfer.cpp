#include "voice_transfer.h"

#include <Arduino.h>
#include <string.h>

#include "voice_recorder.h"

namespace {

constexpr char kDataUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000005";
constexpr char kControlUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000006";
// Android ACKs every four packets and at the end, so every eight-packet
// boundary also has an ACK.
constexpr uint8_t kWindowSize = 8;
constexpr uint8_t kFastPacketSpacingMs = 2;
constexpr uint8_t kMaxPacketSpacingMs = 10;
constexpr unsigned long kAckTimeoutMs = 500;
constexpr uint8_t kMaxRetries = 6;

NimBLECharacteristic* dataCharacteristic = nullptr;
volatile uint8_t chunkSize = 0;
uint32_t pendingAck = 0;
portMUX_TYPE ackMux = portMUX_INITIALIZER_UNLOCKED;

enum class Phase { Start, Data, End };
Phase phase = Phase::Start;
bool sending = false;
bool waitingForWindow = false;
uint8_t session = 0;
uint16_t dataPackets = 0;
uint16_t windowFirst = 0;
uint16_t windowLast = 0;
uint16_t nextSequence = 0;
uint8_t retries = 0;
uint16_t totalRetries = 0;
uint8_t packetSpacingMs = kFastPacketSpacingMs;
unsigned long transferStartedAt = 0;
unsigned long sentAt = 0;
uint8_t packet[244] = {};
size_t packetLength = 0;

class ControlCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
    const std::string value = characteristic->getValue();
    if (value.size() == 2 && static_cast<uint8_t>(value[0]) == 1) {
      const uint8_t requested = static_cast<uint8_t>(value[1]);
      chunkSize = requested <= 240 ? requested : 240;
    } else if (value.size() == 4 && static_cast<uint8_t>(value[0]) == 2) {
      const uint8_t ackSession = static_cast<uint8_t>(value[1]);
      const uint16_t sequence = static_cast<uint8_t>(value[2]) |
          (static_cast<uint16_t>(static_cast<uint8_t>(value[3])) << 8);
      portENTER_CRITICAL(&ackMux);
      pendingAck = (1UL << 24) | (static_cast<uint32_t>(ackSession) << 16) |
                   sequence;
      portEXIT_CRITICAL(&ackMux);
    }
  }
};

void preparePacket(uint16_t sequence) {
  packet[1] = session;
  if (sequence == 0) {
    const uint32_t count = voiceSampleCount();
    packet[0] = 1;
    for (int i = 0; i < 4; ++i) packet[2 + i] = count >> (8 * i);
    packet[6] = 1;  // IMA ADPCM; low nibble first, predictor and index start at zero.
    packetLength = 7;
  } else if (sequence <= dataPackets) {
    packet[0] = 2;
    packet[2] = sequence;
    packet[3] = sequence >> 8;
    const size_t offset = static_cast<size_t>(sequence - 1) * chunkSize;
    const size_t remaining = voiceEncodedSize() - offset;
    const size_t length = min(static_cast<size_t>(chunkSize), remaining);
    memcpy(packet + 4, voiceEncodedData() + offset, length);
    packetLength = length + 4;
  } else {
    packet[0] = 3;
    packet[2] = sequence;
    packet[3] = sequence >> 8;
    packetLength = 4;
  }
}

bool sendPacket() {
  sentAt = millis();
  return dataCharacteristic->notify(packet, packetLength);
}

void beginWindow(uint16_t first) {
  windowFirst = first;
  const uint16_t boundary = ((first - 1) / kWindowSize + 1) * kWindowSize;
  windowLast = min(boundary, dataPackets);
  nextSequence = first;
  waitingForWindow = false;
  retries = 0;
}

void finish(bool success) {
  Serial.printf("Voice uplink: %s, %lu ms, %u bytes, %u retries\n",
                success ? "complete" : "failed", millis() - transferStartedAt,
                static_cast<unsigned>(voiceEncodedSize()), totalRetries);
  sending = false;
  voiceTransferFinished(success);
}

uint32_t takeAck() {
  portENTER_CRITICAL(&ackMux);
  const uint32_t ack = pendingAck;
  pendingAck = 0;
  portEXIT_CRITICAL(&ackMux);
  return ack;
}

}  // namespace

void voiceTransferBegin(NimBLEService* service) {
  dataCharacteristic = service->createCharacteristic(
      kDataUuid, NIMBLE_PROPERTY::NOTIFY);
  NimBLECharacteristic* control = service->createCharacteristic(
      kControlUuid, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  control->setCallbacks(new ControlCallbacks());
}

void voiceTransferReset() {
  voiceTransferClearConfiguration();
  takeAck();
  if (sending) finish(false);
}

void voiceTransferClearConfiguration() { chunkSize = 0; }

bool voiceTransferConfigured() { return chunkSize != 0; }
bool voiceTransferSending() { return sending; }

void voiceTransferUpdate(bool connected) {
  if (!connected || chunkSize == 0) {
    if (sending) finish(false);
    return;
  }
  if (!sending) {
    if (!voiceReady()) return;
    const size_t count = (voiceEncodedSize() + chunkSize - 1) / chunkSize;
    if (count == 0 || count >= UINT16_MAX) {
      voiceTransferFinished(false);
      return;
    }
    dataPackets = static_cast<uint16_t>(count);
    ++session;
    retries = 0;
    totalRetries = 0;
    packetSpacingMs = kFastPacketSpacingMs;
    transferStartedAt = millis();
    takeAck();
    phase = Phase::Start;
    sending = true;
    voiceTransferStarted();
    preparePacket(0);
    sendPacket();
    return;
  }

  const uint32_t ack = takeAck();
  if ((ack & (1UL << 24)) && static_cast<uint8_t>(ack >> 16) == session) {
    const uint16_t sequence = ack;
    if (phase == Phase::Start && sequence == 0) {
      phase = Phase::Data;
      beginWindow(1);
      return;
    }
    if (phase == Phase::Data && waitingForWindow && sequence == windowLast) {
      if (retries == 0 && packetSpacingMs > kFastPacketSpacingMs) {
        --packetSpacingMs;
      }
      if (sequence == dataPackets) {
        phase = Phase::End;
        retries = 0;
        preparePacket(dataPackets + 1);
        sendPacket();
      } else {
        beginWindow(sequence + 1);
      }
      return;
    }
    if (phase == Phase::End && sequence == dataPackets + 1) {
      finish(true);
      return;
    }
  }

  if (phase == Phase::Data && !waitingForWindow) {
    if (millis() - sentAt < packetSpacingMs) return;
    preparePacket(nextSequence);
    if (sendPacket()) {
      if (nextSequence == windowLast) {
        waitingForWindow = true;
      } else {
        ++nextSequence;
      }
    } else if (packetSpacingMs < kMaxPacketSpacingMs) {
      ++packetSpacingMs;
    }
    return;
  }

  if (millis() - sentAt < kAckTimeoutMs) return;
  if (++retries > kMaxRetries) {
    finish(false);
  } else if (phase == Phase::Data) {
    ++totalRetries;
    packetSpacingMs = min(static_cast<int>(packetSpacingMs) + 2,
                          static_cast<int>(kMaxPacketSpacingMs));
    nextSequence = windowFirst;
    waitingForWindow = false;
  } else {
    ++totalRetries;
    sendPacket();
  }
}
