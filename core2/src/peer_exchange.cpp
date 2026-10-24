#include "peer_exchange.h"

#include <cstring>
#include <string>

#include "peer_distance.h"
#include "pet_config.h"

namespace {

constexpr char kServiceUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000001";
constexpr char kPeerStatusUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000004";
constexpr char kPeerRequestUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000009";
constexpr float kExchangeDistanceMeters = 0.1f;
constexpr float kRearmDistanceMeters = 0.15f;
constexpr unsigned long kStableMs = 700;
constexpr unsigned long kFreshMs = 800;
constexpr unsigned long kRequestFreshMs = 6000;
constexpr unsigned long kRetryMs = 5000;
constexpr uint32_t kConnectTimeoutMs = 3000;
constexpr size_t kMaxPetId = 64;
constexpr size_t kRequestHeader = 30;  // X, version, sender ID, tx, sequence, lengths.

NimBLECharacteristic* peerStatus = nullptr;
String localDeviceId;
portMUX_TYPE requestMux = portMUX_INITIALIZER_UNLOCKED;
bool requestReady = false;
uint8_t requestBytes[kRequestHeader + 2 * kMaxPetId] = {};
size_t requestLength = 0;
char requestAddress[18] = {};
String nearAddress;
unsigned long nearSince = 0;
uint32_t lastNearSeenAt = 0;
uint8_t nearSamples = 0;
unsigned long lastAttempt = 0;
bool armed = true;

String compactAddress(const char* address) {
  String id(address);
  id.replace(":", "");
  id.toUpperCase();
  return id;
}

bool validPetId(const String& id) {
  if (id.isEmpty() || id.length() > kMaxPetId) return false;
  for (size_t i = 0; i < id.length(); ++i) {
    const char c = id[i];
    if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
          (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
  }
  return true;
}

String jsonString(const String& json, const char* key) {
  const String marker = String("\"") + key + "\":\"";
  const int start = json.indexOf(marker);
  if (start < 0) return "";
  const int from = start + marker.length();
  const int end = json.indexOf('"', from);
  return end < 0 ? "" : json.substring(from, end);
}

bool jsonSequence(const String& json, uint32_t& sequence) {
  const String marker = "\"sequence\":";
  const int start = json.indexOf(marker);
  if (start < 0) return false;
  int at = start + marker.length();
  if (at >= static_cast<int>(json.length()) || json[at] < '0' || json[at] > '9')
    return false;
  uint32_t value = 0;
  while (at < static_cast<int>(json.length()) && json[at] >= '0' &&
         json[at] <= '9') {
    const uint8_t digit = json[at++] - '0';
    if (value > (UINT32_MAX - digit) / 10) return false;
    value = value * 10 + digit;
  }
  sequence = value;
  return true;
}

uint64_t idValue(const String& text) {
  uint64_t value = 0;
  for (size_t i = 0; i < text.length(); ++i) {
    const char c = text[i];
    value = (value << 4) | (c <= '9' ? c - '0' : c - 'A' + 10);
  }
  return value;
}

String transactionText(uint64_t value) {
  char text[17];
  snprintf(text, sizeof(text), "%016llX", static_cast<unsigned long long>(value));
  return String(text);
}

uint64_t transactionValue(const String& firstId, const String& secondId,
                          const String& firstPet, const String& secondPet,
                          uint32_t firstSequence, uint32_t secondSequence) {
  uint64_t hash = 1469598103934665603ULL;
  auto add = [&hash](uint8_t byte) {
    hash ^= byte;
    hash *= 1099511628211ULL;
  };
  const uint64_t first = idValue(firstId), second = idValue(secondId);
  for (int shift = 0; shift < 48; shift += 8) {
    add(static_cast<uint8_t>(first >> shift));
    add(static_cast<uint8_t>(second >> shift));
  }
  for (size_t i = 0; i < firstPet.length(); ++i) add(firstPet[i]);
  add(0);
  for (size_t i = 0; i < secondPet.length(); ++i) add(secondPet[i]);
  for (int shift = 0; shift < 32; shift += 8) {
    add(static_cast<uint8_t>(firstSequence >> shift));
    add(static_cast<uint8_t>(secondSequence >> shift));
  }
  return hash;
}

void updatePeerStatus() {
  if (!peerStatus) return;
  String json = "{\"deviceId\":\"" + localDeviceId +
      "\",\"sequence\":" + String(petConfigExchangeSequence());
  if (petConfigExchangePending()) {
    json += ",\"pendingTx\":\"" + petConfigExchangeTransactionId() +
            "\",\"pendingPeer\":\"" + petConfigExchangePeerId() +
            "\",\"pendingGiven\":\"" + petConfigExchangeGivenId() +
            "\",\"pendingGot\":\"" + petConfigExchangeGotId() + "\"}";
  } else {
    json += ",\"petId\":\"" + petConfigId() + "\",\"pendingTx\":\"\"}";
  }
  peerStatus->setValue(json.c_str());
}

class RequestCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo& info) override {
    const std::string value = characteristic->getValue();
    if (value.size() < kRequestHeader || value.size() > sizeof(requestBytes))
      return;
    const std::string address = info.getAddress().toString();
    if (address.size() != 17) return;
    portENTER_CRITICAL(&requestMux);
    if (!requestReady) {
      memcpy(requestBytes, value.data(), value.size());
      requestLength = value.size();
      memcpy(requestAddress, address.c_str(), 18);
      requestReady = true;
    }
    portEXIT_CRITICAL(&requestMux);
  }
};

RequestCallbacks requestCallbacks;

void processRequest(bool audioBusy) {
  uint8_t bytes[sizeof(requestBytes)];
  char address[18];
  size_t length = 0;
  portENTER_CRITICAL(&requestMux);
  if (requestReady) {
    length = requestLength;
    memcpy(bytes, requestBytes, length);
    memcpy(address, requestAddress, sizeof(address));
    requestReady = false;
  }
  portEXIT_CRITICAL(&requestMux);
  if (length == 0 || audioBusy || bytes[0] != 'X' || bytes[1] != 1) return;
  const size_t senderPetLength = bytes[28], expectedPetLength = bytes[29];
  if (senderPetLength == 0 || senderPetLength > kMaxPetId ||
      expectedPetLength == 0 || expectedPetLength > kMaxPetId ||
      length != kRequestHeader + senderPetLength + expectedPetLength) return;
  const String senderId(reinterpret_cast<const char*>(bytes + 2), 12);
  const String senderPet(reinterpret_cast<const char*>(bytes + kRequestHeader),
                         senderPetLength);
  const String expectedPet(reinterpret_cast<const char*>(bytes + kRequestHeader +
                                                        senderPetLength),
                           expectedPetLength);
  if (senderId != compactAddress(address) || senderId >= localDeviceId ||
      !validPetId(senderPet) || expectedPet != petConfigId() ||
      senderPet == expectedPet) return;
  PeerDistanceReading reading;
  // GATT discovery can take several seconds after the last advertisement.
  if (!peerDistanceReadAddress(address, reading, kRequestFreshMs) ||
      reading.meters <= 0 || reading.meters > kExchangeDistanceMeters) return;
  uint64_t transaction = 0;
  for (int i = 0; i < 8; ++i)
    transaction |= static_cast<uint64_t>(bytes[14 + i]) << (8 * i);
  uint32_t senderSequence = 0;
  for (int i = 0; i < 4; ++i)
    senderSequence |= static_cast<uint32_t>(bytes[22 + i]) << (8 * i);
  if (bytes[26] != 0 || bytes[27] != 0 ||
      transaction != transactionValue(senderId, localDeviceId, senderPet,
                                       expectedPet, senderSequence,
                                       petConfigExchangeSequence())) return;
  const String tx = transactionText(transaction);
  if (petConfigExchangePending()) {
    if (petConfigExchangeTransactionId() != tx ||
        petConfigExchangePeerId() != senderId ||
        petConfigExchangeGotId() != senderPet ||
        petConfigExchangeGivenId() != expectedPet) return;
  } else if (!petConfigCreateExchange(tx, senderId, expectedPet,
                                       senderPet, reading.meters)) {
    return;
  }
  armed = false;
  updatePeerStatus();
}

bool readPeerStatus(NimBLERemoteCharacteristic* remote, String& data) {
  if (!remote || !remote->canRead()) return false;
  const NimBLEAttValue value = remote->readValue();
  if (value.size() == 0 || value.size() > 400) return false;
  data = String(std::string(reinterpret_cast<const char*>(value.data()),
                            value.size()).c_str());
  return true;
}

void tryLeader(const PeerDistanceReading& reading) {
  if (petConfigExchangePending() || !validPetId(petConfigId())) return;
  const String peerId = compactAddress(reading.address);
  if (peerId.length() != 12 || localDeviceId >= peerId) return;
  NimBLEScan* scan = NimBLEDevice::getScan();
  if (scan->isScanning()) scan->stop();
  NimBLEClient* client = NimBLEDevice::createClient();
  if (!client) return;
  client->setConnectTimeout(kConnectTimeoutMs);
  const NimBLEAddress address(std::string(reading.address), reading.addressType);
  if (client->connect(address)) {
    NimBLERemoteService* service = client->getService(kServiceUuid);
    NimBLERemoteCharacteristic* status =
        service ? service->getCharacteristic(kPeerStatusUuid) : nullptr;
    NimBLERemoteCharacteristic* request =
        service ? service->getCharacteristic(kPeerRequestUuid) : nullptr;
    String data;
    uint32_t peerSequence = 0;
    if (readPeerStatus(status, data) && jsonString(data, "deviceId") == peerId &&
        !jsonString(data, "pendingTx").isEmpty()) {
      const String tx = jsonString(data, "pendingTx");
      const String given = jsonString(data, "pendingGot");
      const String got = jsonString(data, "pendingGiven");
      if (jsonString(data, "pendingPeer") == localDeviceId &&
          jsonSequence(data, peerSequence) &&
          validPetId(given) && validPetId(got) &&
          transactionText(transactionValue(localDeviceId, peerId, given, got,
                          petConfigExchangeSequence(), peerSequence)) == tx &&
          petConfigCreateExchange(tx, peerId, given, got, reading.meters))
        armed = false;
    } else if (request && request->canWrite() &&
               jsonString(data, "deviceId") == peerId &&
               jsonSequence(data, peerSequence)) {
      const String peerPet = jsonString(data, "petId");
      const String ownPet = petConfigId();
      if (validPetId(peerPet) && peerPet != ownPet) {
        const uint64_t txValue = transactionValue(localDeviceId, peerId, ownPet,
            peerPet, petConfigExchangeSequence(), peerSequence);
        const String tx = transactionText(txValue);
        uint8_t packet[kRequestHeader + 2 * kMaxPetId] = {};
        packet[0] = 'X';
        packet[1] = 1;
        memcpy(packet + 2, localDeviceId.c_str(), 12);
        for (int i = 0; i < 8; ++i) packet[14 + i] = txValue >> (8 * i);
        const uint32_t sequence = petConfigExchangeSequence();
        for (int i = 0; i < 4; ++i) packet[22 + i] = sequence >> (8 * i);
        packet[28] = ownPet.length();
        packet[29] = peerPet.length();
        memcpy(packet + kRequestHeader, ownPet.c_str(), ownPet.length());
        memcpy(packet + kRequestHeader + ownPet.length(), peerPet.c_str(),
               peerPet.length());
        const size_t length = kRequestHeader + ownPet.length() + peerPet.length();
        // NimBLE uses a long write when the negotiated MTU is too small.
        if (request->writeValue(packet, length, true)) {
          const unsigned long deadline = millis() + 1800;
          do {
            delay(80);
            if (readPeerStatus(status, data) && jsonString(data, "pendingTx") == tx) {
              if (petConfigCreateExchange(tx, peerId, ownPet,
                                          peerPet, reading.meters))
                armed = false;
              break;
            }
          } while (static_cast<int32_t>(millis() - deadline) < 0);
        }
      }
    }
    client->disconnect();
  }
  NimBLEDevice::deleteClient(client);
}

}  // namespace

void peerExchangeBegin(NimBLEService* service, const String& deviceId) {
  localDeviceId = deviceId;
  peerStatus = service->createCharacteristic(kPeerStatusUuid, NIMBLE_PROPERTY::READ);
  updatePeerStatus();
  NimBLECharacteristic* request = service->createCharacteristic(
      kPeerRequestUuid, NIMBLE_PROPERTY::WRITE);
  request->setCallbacks(&requestCallbacks);
}

void peerExchangeUpdate(bool audioBusy) {
  processRequest(audioBusy);
  static uint32_t lastRevision = UINT32_MAX;
  if (petConfigRevision() != lastRevision) {
    lastRevision = petConfigRevision();
    updatePeerStatus();
  }
  PeerDistanceReading reading;
  const unsigned long now = millis();
  if (!peerDistanceRead(reading) || now - reading.seenAt > kFreshMs ||
      reading.meters > kRearmDistanceMeters) {
    armed = true;
    nearAddress = "";
    nearSince = 0;
    nearSamples = 0;
    return;
  }
  if (reading.meters <= 0 || reading.meters > kExchangeDistanceMeters ||
      audioBusy || petConfigExchangePending() || !armed) {
    nearAddress = "";
    nearSince = 0;
    nearSamples = 0;
    return;
  }
  if (nearAddress != reading.address) {
    nearAddress = reading.address;
    nearSince = now;
    lastNearSeenAt = reading.seenAt;
    nearSamples = 1;
    return;
  }
  if (reading.seenAt != lastNearSeenAt) {
    lastNearSeenAt = reading.seenAt;
    if (nearSamples < 3) ++nearSamples;
  }
  if (nearSamples < 3 || now - nearSince < kStableMs ||
      now - lastAttempt < kRetryMs) return;
  lastAttempt = now;
  tryLeader(reading);
}
