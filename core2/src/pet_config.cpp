#include "pet_config.h"

#include <Preferences.h>

#include <cstring>
#include <string>
#include <math.h>

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
volatile uint16_t androidConnectionHandle = UINT16_MAX;
String pendingTransactionId;
String pendingPeerDeviceId;
String pendingGivenPetId;
String pendingGotPetId;
float pendingDistanceMeters = 0;
uint32_t exchangeSequence = 0;
String lastResultTransactionId;
String lastResult;
bool configSyncedThisConnection = false;
bool resultAckPending = false;
uint64_t resultAckId = 0;
unsigned long lastPendingNotify = 0;

enum class OutgoingKind { None, ConfigAck, ExchangePending, ResultAck };
OutgoingKind outgoingKind = OutgoingKind::None;

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

bool validTransactionId(const String& id) {
  if (id.length() != 16) return false;
  for (size_t i = 0; i < id.length(); ++i) {
    const char c = id[i];
    if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'))) return false;
  }
  return true;
}

bool validDeviceId(const String& id) {
  if (id.length() != 12) return false;
  for (size_t i = 0; i < id.length(); ++i) {
    const char c = id[i];
    if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'))) return false;
  }
  return true;
}

uint64_t parseId(const String& id) {
  uint64_t value = 0;
  for (size_t i = 0; i < id.length(); ++i) {
    const char c = id[i];
    value = (value << 4) | (c <= '9' ? c - '0' : c - 'A' + 10);
  }
  return value;
}

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

bool startOutgoing(uint64_t id, const String& json, OutgoingKind kind) {
  const size_t count = (json.length() + kPayloadSize - 1) / kPayloadSize;
  if (txActive || count == 0 || count > 255) return false;
  txJson = json;
  txId = id;
  txSequence = 0;
  txCount = static_cast<uint8_t>(count);
  txRetries = 0;
  txActive = true;
  outgoingKind = kind;
  sendOutgoingFrame();
  return true;
}

void startConfigAck(uint64_t id) {
  const String json = "{\"type\":\"pet_config_ack\",\"transactionId\":\"" +
                      idText(id) + "\",\"status\":\"received\",\"deviceId\":\"" +
                      localDeviceId + "\"}";
  if (startOutgoing(id, json, OutgoingKind::ConfigAck))
    configSyncedThisConnection = true;
}

void startResultAck(uint64_t id) {
  const String json = "{\"type\":\"exchange_result_ack\",\"transactionId\":\"" +
                      idText(id) + "\",\"status\":\"received\"}";
  if (startOutgoing(id, json, OutgoingKind::ResultAck)) resultAckPending = false;
}

void clearPendingExchange() {
  pendingTransactionId = "";
  pendingPeerDeviceId = "";
  pendingGivenPetId = "";
  pendingGotPetId = "";
  pendingDistanceMeters = 0;
  preferences.remove("exTx");
  preferences.remove("exPeer");
  preferences.remove("exGiven");
  preferences.remove("exGot");
  preferences.remove("exDist");
  ++revision;
}

void handleExchangeResult(const String& json, uint64_t id) {
  String transactionId, result, givenPetId, gotPetId;
  if (!jsonString(json, "transactionId", transactionId) ||
      transactionId != idText(id) ||
      !jsonString(json, "result", result) ||
      !jsonString(json, "givenPetId", givenPetId) ||
      !jsonString(json, "gotPetId", gotPetId)) return;
  const bool confirmed = result == "done" || result == "already_done";
  if (!pendingTransactionId.isEmpty() && transactionId == pendingTransactionId &&
      givenPetId == pendingGivenPetId && gotPetId == pendingGotPetId &&
      (confirmed || result == "rejected" || result == "confirming")) {
    if (result != "confirming") {
      const String& finalPetId = confirmed ? pendingGotPetId : pendingGivenPetId;
      if (configuredPetId != finalPetId) {
        if (preferences.putString("petId", finalPetId) == 0) return;
        configuredPetId = finalPetId;
      }
      if (preferences.putUInt("exSeq", exchangeSequence + 1) != sizeof(uint32_t) ||
          preferences.putString("exDone", transactionId + ":" + result) == 0)
        return;
      ++exchangeSequence;
      lastResultTransactionId = transactionId;
      lastResult = result;
      clearPendingExchange();
      Serial.printf("EXCHANGE result %s tx=%s pet=%s\n", result.c_str(),
                    transactionId.c_str(), configuredPetId.c_str());
    }
    resultAckId = id;
    resultAckPending = true;
  } else if (transactionId == lastResultTransactionId &&
             (result == lastResult ||
              (confirmed && (lastResult == "done" || lastResult == "already_done")))) {
    resultAckId = id;
    resultAckPending = true;
  }
}

void processIncoming(const String& json, uint64_t id) {
  String type;
  if (!jsonString(json, "type", type)) return;
  if (type == "exchange_result") {
    handleExchangeResult(json, id);
    return;
  }
  String transactionId, deviceId, petId;
  if (type != "pet_config" ||
      !jsonString(json, "transactionId", transactionId) ||
      transactionId != idText(id) ||
      !jsonString(json, "deviceId", deviceId) ||
      deviceId != localDeviceId ||
      !jsonString(json, "petId", petId) || !validPetId(petId) ||
      (!pendingTransactionId.isEmpty() &&
       petId != pendingGivenPetId && petId != pendingGotPetId)) return;
  if (petId == configuredPetId || preferences.putString("petId", petId) > 0) {
    if (petId != configuredPetId) {
      configuredPetId = petId;
      ++revision;
    }
    startConfigAck(id);
  }
}

class CommandCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo& info) override {
    if (info.getConnHandle() != androidConnectionHandle) return;
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
  exchangeSequence = preferences.getUInt("exSeq", 0);
  pendingTransactionId = preferences.getString("exTx", "");
  pendingPeerDeviceId = preferences.getString("exPeer", "");
  pendingGivenPetId = preferences.getString("exGiven", "");
  pendingGotPetId = preferences.getString("exGot", "");
  pendingDistanceMeters = preferences.getFloat("exDist", 0);
  const String done = preferences.getString("exDone", "");
  if (done.length() > 17 && done[16] == ':') {
    lastResultTransactionId = done.substring(0, 16);
    lastResult = done.substring(17);
  }
  if (!pendingTransactionId.isEmpty()) {
    // A reboot abandons the candidate. Advance the sequence so a new encounter
    // cannot reuse its transaction ID or recover it from the other Core2.
    ++exchangeSequence;
    preferences.putUInt("exSeq", exchangeSequence);
    clearPendingExchange();
  }
  NimBLECharacteristic* command = service->createCharacteristic(
      kCommandUuid, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  command->setCallbacks(new CommandCallbacks());
}

void petConfigSetAndroidConnection(uint16_t handle) {
  androidConnectionHandle = handle;
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
  if (configPending && (!txActive || outgoingKind == OutgoingKind::ExchangePending)) {
    if (outgoingKind == OutgoingKind::ExchangePending) {
      txActive = false;
      txJson = "";
      outgoingKind = OutgoingKind::None;
    }
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
      outgoingKind = OutgoingKind::None;
    } else {
      ++txSequence;
      txRetries = 0;
      sendOutgoingFrame();
    }
  }
  if (ack) sendFrameAck(ackId, ackSequence);
  if (pending) processIncoming(String(json), id);
  if (resultAckPending && txActive && outgoingKind == OutgoingKind::ExchangePending) {
    txActive = false;
    txJson = "";
    outgoingKind = OutgoingKind::None;
  }
  if (resultAckPending && !txActive) startResultAck(resultAckId);
  if (txActive && millis() - txSentAt >= kRetryMs) {
    if (txRetries >= kMaxRetries) {
      txActive = false;
      txJson = "";
      if (outgoingKind == OutgoingKind::ResultAck) resultAckPending = true;
      outgoingKind = OutgoingKind::None;
    } else {
      ++txRetries;
      sendOutgoingFrame();
    }
  }
  if (configSyncedThisConnection && !pendingTransactionId.isEmpty() &&
      !txActive && !resultAckPending &&
      millis() - lastPendingNotify >= 3000) {
    const String json = "{\"type\":\"exchange_pending\",\"transactionId\":\"" +
        pendingTransactionId + "\",\"myDeviceId\":\"" + localDeviceId +
        "\",\"peerDeviceId\":\"" + pendingPeerDeviceId +
        "\",\"givenPetId\":\"" + pendingGivenPetId +
        "\",\"gotPetId\":\"" + pendingGotPetId +
        "\",\"distanceMeters\":" + String(pendingDistanceMeters, 3) + "}";
    if (startOutgoing(parseId(pendingTransactionId), json,
                      OutgoingKind::ExchangePending)) lastPendingNotify = millis();
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
  outgoingKind = OutgoingKind::None;
  configSyncedThisConnection = false;
  resultAckPending = false;
}

const String& petConfigId() { return configuredPetId; }
uint32_t petConfigRevision() { return revision; }

bool petConfigCreateExchange(const String& transactionId,
                             const String& peerDeviceId,
                             const String& givenPetId,
                             const String& gotPetId, float distanceMeters) {
  if (!pendingTransactionId.isEmpty() || !validTransactionId(transactionId) ||
      !validDeviceId(peerDeviceId) || peerDeviceId == localDeviceId ||
      !validPetId(givenPetId) || !validPetId(gotPetId) ||
      (configuredPetId != givenPetId && configuredPetId != gotPetId) ||
      gotPetId == givenPetId || !isfinite(distanceMeters) ||
      distanceMeters <= 0 || distanceMeters > 0.1f) return false;
  const float savedDistance = fminf(0.1f,
      fmaxf(0.001f, ceilf(distanceMeters * 1000.0f) / 1000.0f));
  if (preferences.putString("exPeer", peerDeviceId) == 0 ||
      preferences.putString("exGiven", givenPetId) == 0 ||
      preferences.putString("exGot", gotPetId) == 0 ||
      preferences.putFloat("exDist", savedDistance) != sizeof(float) ||
      preferences.putString("exTx", transactionId) == 0) {
    preferences.remove("exTx");
    preferences.remove("exPeer");
    preferences.remove("exGiven");
    preferences.remove("exGot");
    preferences.remove("exDist");
    return false;
  }
  pendingTransactionId = transactionId;
  pendingPeerDeviceId = peerDeviceId;
  pendingGivenPetId = givenPetId;
  pendingGotPetId = gotPetId;
  pendingDistanceMeters = savedDistance;
  lastPendingNotify = millis() - 3000;
  ++revision;
  Serial.printf("EXCHANGE pending tx=%s peer=%s distance=%.3f\n",
                transactionId.c_str(), peerDeviceId.c_str(), savedDistance);
  return true;
}

bool petConfigExchangePending() { return !pendingTransactionId.isEmpty(); }
const String& petConfigExchangeTransactionId() { return pendingTransactionId; }
const String& petConfigExchangePeerId() { return pendingPeerDeviceId; }
const String& petConfigExchangeGivenId() { return pendingGivenPetId; }
const String& petConfigExchangeGotId() { return pendingGotPetId; }
uint32_t petConfigExchangeSequence() { return exchangeSequence; }
const char* petConfigExchangeStatus() {
  if (!pendingTransactionId.isEmpty()) return "PENDING";
  if (configuredPetId.isEmpty()) return "NO PET";
  if (lastResult == "rejected") return "REJECTED";
  if (lastResult == "done" || lastResult == "already_done") return "DONE";
  return "READY";
}
