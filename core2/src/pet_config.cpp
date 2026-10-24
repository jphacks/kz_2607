#include "pet_config.h"

#include <Preferences.h>

#include <cstring>
#include <string>

namespace {

constexpr char kCommandUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000003";
constexpr size_t kFrameSize = 20;
constexpr size_t kPayloadSize = 5;
constexpr size_t kMaxJsonSize = 1024;
constexpr size_t kMaxPetIdSize = 128;
constexpr unsigned long kRetryMs = 500;
constexpr uint8_t kMaxRetries = 3;

Preferences preferences;
NimBLECharacteristic* statusCharacteristic = nullptr;
String localDeviceId;
String configuredPetId;
uint32_t revision = 0;

portMUX_TYPE queueMux = portMUX_INITIALIZER_UNLOCKED;
bool frameAckPending = false;
uint64_t frameAckId = 0;
uint8_t frameAckSequence = 0;
bool configPending = false;
uint64_t pendingId = 0;
char pendingJson[kMaxJsonSize + 1] = {};
bool outgoingAckPending = false;
uint64_t outgoingAckId = 0;
uint8_t outgoingAckSequence = 0;

uint64_t rxId = 0;
uint8_t rxExpected = 0;
uint8_t rxCount = 0;
size_t rxLength = 0;
char rxJson[kMaxJsonSize + 1] = {};

bool txActive = false;
uint64_t txId = 0;
uint8_t txSequence = 0;
uint8_t txCount = 0;
uint8_t txRetries = 0;
unsigned long txSentAt = 0;
String txJson;

uint64_t readId(const uint8_t* frame) {
  uint64_t id = 0;
  for (size_t i = 0; i < 8; ++i) {
    id |= static_cast<uint64_t>(frame[4 + i]) << (8 * i);
  }
  return id;
}

void writeId(uint8_t* frame, uint64_t id) {
  for (size_t i = 0; i < 8; ++i) {
    frame[4 + i] = static_cast<uint8_t>(id >> (8 * i));
  }
}

String idText(uint64_t id) {
  char text[17];
  snprintf(text, sizeof(text), "%016llX", static_cast<unsigned long long>(id));
  return String(text);
}

bool jsonString(const String& json, const char* key, String& value) {
  const String marker = String("\"") + key + "\"";
  const int at = json.indexOf(marker);
  if (at < 0 || json.indexOf(marker, at + marker.length()) >= 0) return false;
  int start = at + marker.length();
  while (start < static_cast<int>(json.length()) && json[start] == ' ') ++start;
  if (start >= static_cast<int>(json.length()) || json[start++] != ':') return false;
  while (start < static_cast<int>(json.length()) && json[start] == ' ') ++start;
  if (start >= static_cast<int>(json.length()) || json[start++] != '"') return false;
  const int end = json.indexOf('"', start);
  if (end < 0) return false;
  value = json.substring(start, end);
  return value.indexOf('\\') < 0;
}

bool validPetId(const String& id) {
  if (id.isEmpty() || id.length() > kMaxPetIdSize) return false;
  for (size_t i = 0; i < id.length(); ++i) {
    const char c = id[i];
    if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
          (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
  }
  return true;
}

void sendFrameAck(uint64_t id, uint8_t sequence) {
  if (!statusCharacteristic) return;
  uint8_t frame[kFrameSize] = {};
  frame[0] = 'F';
  frame[1] = 1;
  frame[2] = 2;
  writeId(frame, id);
  frame[12] = sequence;
  statusCharacteristic->notify(frame, sizeof(frame));
}

void sendOutgoingFrame() {
  if (!txActive || !statusCharacteristic) return;
  const size_t start = static_cast<size_t>(txSequence) * kPayloadSize;
  const size_t remaining = txJson.length() - start;
  const size_t length = remaining < kPayloadSize ? remaining : kPayloadSize;
  uint8_t frame[kFrameSize] = {};
  frame[0] = 'F';
  frame[1] = 1;
  frame[2] = 1;
  writeId(frame, txId);
  frame[12] = txSequence;
  frame[13] = txCount;
  frame[14] = static_cast<uint8_t>(length);
  memcpy(frame + 15, txJson.c_str() + start, length);
  statusCharacteristic->notify(frame, sizeof(frame));
  txSentAt = millis();
}

void startConfigAck(uint64_t id) {
  txJson = "{\"type\":\"pet_config_ack\",\"transactionId\":\"" +
           idText(id) + "\",\"status\":\"received\",\"deviceId\":\"" +
           localDeviceId + "\"}";
  const size_t count = (txJson.length() + kPayloadSize - 1) / kPayloadSize;
  if (count == 0 || count > 255) return;
  txId = id;
  txSequence = 0;
  txCount = static_cast<uint8_t>(count);
  txRetries = 0;
  txActive = true;
  sendOutgoingFrame();
}

class CommandCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
    const std::string value = characteristic->getValue();
    if (value.size() != kFrameSize) return;
    const auto* frame = reinterpret_cast<const uint8_t*>(value.data());
    if (frame[0] != 'F' || frame[1] != 1 || frame[3] != 0) return;
    const uint64_t id = readId(frame);
    const uint8_t sequence = frame[12];
    if (frame[2] == 2) {
      if (frame[13] == 0 && frame[14] == 0) {
        portENTER_CRITICAL(&queueMux);
        outgoingAckId = id;
        outgoingAckSequence = sequence;
        outgoingAckPending = true;
        portEXIT_CRITICAL(&queueMux);
      }
      return;
    }
    if (frame[2] != 1 || frame[13] == 0 ||
        sequence >= frame[13] || frame[14] == 0 ||
        frame[14] > kPayloadSize) return;

    if (id != rxId || (sequence == 0 && rxExpected == rxCount)) {
      if (sequence != 0 || configPending) return;
      rxId = id;
      rxExpected = 0;
      rxCount = frame[13];
      rxLength = 0;
    }
    if (frame[13] != rxCount) return;
    if (sequence < rxExpected) {
      portENTER_CRITICAL(&queueMux);
      frameAckId = id;
      frameAckSequence = sequence;
      frameAckPending = true;
      portEXIT_CRITICAL(&queueMux);
      return;
    }
    if (sequence != rxExpected || rxLength + frame[14] > kMaxJsonSize) return;
    memcpy(rxJson + rxLength, frame + 15, frame[14]);
    rxLength += frame[14];
    ++rxExpected;
    if (rxExpected == rxCount) {
      rxJson[rxLength] = '\0';
      portENTER_CRITICAL(&queueMux);
      if (!configPending) {
        memcpy(pendingJson, rxJson, rxLength + 1);
        pendingId = id;
        configPending = true;
      }
      portEXIT_CRITICAL(&queueMux);
    }
    portENTER_CRITICAL(&queueMux);
    frameAckId = id;
    frameAckSequence = sequence;
    frameAckPending = true;
    portEXIT_CRITICAL(&queueMux);
  }
};

}  // namespace

void petConfigBegin(NimBLEService* service, NimBLECharacteristic* status,
                    const String& deviceId) {
  statusCharacteristic = status;
  localDeviceId = deviceId;
  preferences.begin("core2", false);
  configuredPetId = preferences.getString("petId", "");
  NimBLECharacteristic* command = service->createCharacteristic(
      kCommandUuid, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  command->setCallbacks(new CommandCallbacks());
}

void petConfigUpdate(bool connected) {
  if (!connected) return;
  bool ack = false;
  uint64_t ackId = 0;
  uint8_t ackSequence = 0;
  bool pending = false;
  uint64_t id = 0;
  char json[kMaxJsonSize + 1];
  bool outgoingAck = false;
  uint64_t acknowledgedId = 0;
  uint8_t acknowledgedSequence = 0;
  portENTER_CRITICAL(&queueMux);
  if (outgoingAckPending) {
    outgoingAck = true;
    acknowledgedId = outgoingAckId;
    acknowledgedSequence = outgoingAckSequence;
    outgoingAckPending = false;
  }
  if (frameAckPending) {
    ack = true;
    ackId = frameAckId;
    ackSequence = frameAckSequence;
    frameAckPending = false;
  }
  if (configPending && !txActive) {
    pending = true;
    id = pendingId;
    memcpy(json, pendingJson, strlen(pendingJson) + 1);
    configPending = false;
  }
  portEXIT_CRITICAL(&queueMux);
  if (outgoingAck && txActive && acknowledgedId == txId &&
      acknowledgedSequence == txSequence) {
    if (txSequence + 1 == txCount) {
      txActive = false;
      txJson = "";
    } else {
      ++txSequence;
      txRetries = 0;
      sendOutgoingFrame();
    }
  }
  if (ack) sendFrameAck(ackId, ackSequence);
  if (pending) {
    const String payload(json);
    String type, transactionId, deviceId, petId;
    if (jsonString(payload, "type", type) && type == "pet_config" &&
        jsonString(payload, "transactionId", transactionId) &&
        transactionId == idText(id) &&
        jsonString(payload, "deviceId", deviceId) &&
        deviceId == localDeviceId &&
        jsonString(payload, "petId", petId) && validPetId(petId)) {
      if (petId == configuredPetId || preferences.putString("petId", petId) > 0) {
        if (petId != configuredPetId) {
          configuredPetId = petId;
          ++revision;
        }
        startConfigAck(id);
      }
    }
  }
  if (txActive && millis() - txSentAt >= kRetryMs) {
    if (txRetries >= kMaxRetries) {
      txActive = false;
      txJson = "";
    } else {
      ++txRetries;
      sendOutgoingFrame();
    }
  }
}

void petConfigReset() {
  portENTER_CRITICAL(&queueMux);
  frameAckPending = false;
  configPending = false;
  outgoingAckPending = false;
  portEXIT_CRITICAL(&queueMux);
  rxId = 0;
  rxExpected = rxCount = 0;
  rxLength = 0;
  txActive = false;
  txJson = "";
}

const String& petConfigId() { return configuredPetId; }
uint32_t petConfigRevision() { return revision; }
