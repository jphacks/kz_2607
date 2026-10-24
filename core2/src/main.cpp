#include <Arduino.h>
#include <M5Unified.h>
#include <NimBLEDevice.h>

#include "voice_recorder.h"
#include "voice_transfer.h"
#include "reply_receiver.h"
#include "peer_distance.h"
#include "pet_config.h"
#include "peer_exchange.h"
#include "step_counter.h"

namespace {

constexpr char kDeviceName[] = "M5StackCore2";
constexpr char kServiceUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000001";
constexpr char kStatusUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000002";
constexpr unsigned long kPeerConnectionAgeMs = 6000;

constexpr int kModeButtonX = 242;
constexpr int kModeButtonY = 74;
constexpr int kModeButtonWidth = 72;
constexpr int kModeButtonHeight = 30;
bool playMode = true;

volatile bool connected = false;
volatile bool connectionChanged = true;
uint16_t peerConnectionHandle = UINT16_MAX;
uint16_t androidConnectionHandle = UINT16_MAX;
String macAddress;
String deviceId;
NimBLECharacteristic* statusCharacteristic = nullptr;

String statusJson() {
  PeerDistanceReading peer;
  const bool found = peerDistanceRead(peer);
  String peerId = found ? String(peer.address) : "";
  if (found) {
    peerId.replace(":", "");
    peerId.toUpperCase();
    peerId = "M5-" + peerId;
  }
  return "{\"id\":\"M5-" + deviceId + "\",\"mac\":\"" + macAddress +
         "\",\"peerId\":\"" + peerId + "\",\"distance\":" +
         String(found ? peer.meters : 0, 3) + ",\"petId\":\"" +
         petConfigId() + "\",\"exchangeStatus\":\"" +
         petConfigExchangeStatus() + "\",\"stepCount\":" +
         String(stepCounterCount()) + "}";
}

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer*, NimBLEConnInfo& info) override {
    const std::string address = info.getAddress().toString();
    PeerDistanceReading peer;
    if (connected || peerDistanceReadAddress(address.c_str(), peer,
                                             kPeerConnectionAgeMs)) {
      peerConnectionHandle = info.getConnHandle();
    } else {
      androidConnectionHandle = info.getConnHandle();
      petConfigSetAndroidConnection(androidConnectionHandle);
      connected = true;
      connectionChanged = true;
    }
    // Keep the Core2 visible to another Core2 while Android is connected.
    NimBLEDevice::startAdvertising();
  }

  void onDisconnect(NimBLEServer*, NimBLEConnInfo& info, int) override {
    if (info.getConnHandle() == peerConnectionHandle) {
      peerConnectionHandle = UINT16_MAX;
    } else if (info.getConnHandle() == androidConnectionHandle) {
      androidConnectionHandle = UINT16_MAX;
      petConfigSetAndroidConnection(UINT16_MAX);
      connected = false;
      connectionChanged = true;
      voiceTransferClearConfiguration();
    }
    NimBLEDevice::startAdvertising();
  }
};

void drawModeButton() {
  M5.Display.fillRoundRect(kModeButtonX, kModeButtonY, kModeButtonWidth,
                           kModeButtonHeight, 5, TFT_DARKGREY);
  M5.Display.setTextColor(TFT_WHITE, TFT_DARKGREY);
  M5.Display.setTextSize(1);
  M5.Display.setCursor(kModeButtonX + (playMode ? 19 : 23), kModeButtonY + 11);
  M5.Display.print(playMode ? "DEBUG" : "PLAY");
}

bool updateScreenMode() {
  if (!M5.Touch.getCount()) return false;
  const auto& touch = M5.Touch.getDetail();
  if (!touch.wasPressed() || touch.x < kModeButtonX ||
      touch.x >= kModeButtonX + kModeButtonWidth ||
      touch.y < kModeButtonY || touch.y >= kModeButtonY + kModeButtonHeight) {
    return false;
  }
  playMode = !playMode;
  return true;
}

void drawScreen() {
  if (playMode) {
    M5.Display.fillScreen(TFT_BLACK);
    drawModeButton();
    return;
  }
  M5.Display.fillScreen(TFT_NAVY);
  M5.Display.setTextColor(TFT_WHITE, TFT_NAVY);
  M5.Display.setTextSize(2);
  M5.Display.setCursor(16, 20);
  M5.Display.print("Core2 BLE");
  M5.Display.setTextSize(1);
  M5.Display.setCursor(190, 11);
  M5.Display.print("STEPS");
  M5.Display.setTextSize(2);
  M5.Display.setCursor(190, 23);
  if (stepCounterAvailable()) {
    M5.Display.print(stepCounterCount());
  } else {
    M5.Display.print("IMU N/A");
  }

  if (petConfigExchangePending()) {
    M5.Display.fillRoundRect(8, 45, M5.Display.width() - 16, 25, 4,
                             TFT_ORANGE);
    M5.Display.setTextColor(TFT_BLACK, TFT_ORANGE);
    M5.Display.setCursor(16, 49);
    M5.Display.print("CANDIDATE SAVED");
  }

  M5.Display.setTextColor(connected ? TFT_GREEN : TFT_YELLOW, TFT_NAVY);
  M5.Display.setCursor(16, 76);
  M5.Display.print(connected ? "CONNECTED" : "WAITING...");

  M5.Display.setTextColor(TFT_WHITE, TFT_NAVY);
  M5.Display.setTextSize(1);
  PeerDistanceReading peer;
  const bool found = peerDistanceRead(peer);
  M5.Display.setCursor(16, 106);
  if (found) {
    M5.Display.printf("PEER: %s", peer.address);
    M5.Display.setTextSize(2);
    M5.Display.setTextColor(
        peer.meters <= 0.1f ? TFT_GREEN : TFT_WHITE, TFT_NAVY);
    M5.Display.setCursor(16, 124);
    if (peer.meters > 20.0f) {
      M5.Display.print("DIST: >20 m");
    } else if (peer.meters < 1.0f) {
      M5.Display.printf("DIST: ~%.2f m", peer.meters);
    } else {
      M5.Display.printf("DIST: ~%.1f m", peer.meters);
    }
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_WHITE, TFT_NAVY);
    M5.Display.setCursor(16, 154);
    M5.Display.printf("RSSI: %d dBm (approx.)", peer.rssi);
  } else {
    M5.Display.print("PEER: SEARCHING...");
    M5.Display.setTextSize(2);
    M5.Display.setCursor(16, 124);
    M5.Display.print("DIST: --");
    M5.Display.setTextSize(1);
  }
  M5.Display.setCursor(16, 169);
  M5.Display.printf("MY MAC: %s", macAddress.c_str());
  M5.Display.setCursor(16, 180);
  const String& petId = petConfigId();
  M5.Display.print("PET ID: ");
  M5.Display.print(petId.isEmpty() ? "--" : petId.substring(0, 42));

  M5.Display.setCursor(16, 192);
  M5.Display.printf("EXCHANGE: %s (<=0.1 m)", petConfigExchangeStatus());
  M5.Display.drawFastHLine(16, 205, M5.Display.width() - 32, TFT_WHITE);
  M5.Display.setCursor(16, 212);
  if (voiceRecording()) {
    M5.Display.printf("Recording: %.1f / 5.0 s", voiceDurationSeconds());
  } else if (replyReceiverReceiving()) {
    M5.Display.printf("%s reply: %u%%",
                      voicePlayingReply() ? "Playing" : "Receiving",
                      replyReceiverProgressPercent());
  } else if (voicePlayingReply()) {
    M5.Display.print("Playing reply...");
  } else if (connected && !voiceTransferConfigured()) {
    M5.Display.print("Open Android voice receiver");
  } else {
    M5.Display.print(voiceMessage());
  }
  M5.Display.setCursor(16, 230);
  M5.Display.print("Hold A to talk");
  drawModeButton();
}

void startBle() {
  NimBLEDevice::init(kDeviceName);
  NimBLEDevice::setMTU(247);
  macAddress = NimBLEDevice::getAddress().toString().c_str();
  deviceId = macAddress;
  deviceId.replace(":", "");
  deviceId.toUpperCase();

  NimBLEServer* server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEService* service = server->createService(kServiceUuid);
  statusCharacteristic = service->createCharacteristic(
      kStatusUuid, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
  petConfigBegin(service, statusCharacteristic, deviceId);
  peerExchangeBegin(service, deviceId);
  statusCharacteristic->setValue(statusJson().c_str());
  voiceTransferBegin(service);
  replyReceiverBegin(service);
  server->start();

  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(kServiceUuid);
  advertising->enableScanResponse(true);
  advertising->setName(kDeviceName);
  advertising->start();
  peerDistanceBegin();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  M5.begin(M5.config());
  voiceBegin();
  stepCounterBegin();
  startBle();
  drawScreen();
}

void loop() {
  M5.update();
  const bool modeChanged = updateScreenMode();
  voiceUpdate(connected && voiceTransferConfigured() && !replyReceiverBusy() &&
              !petConfigExchangePending());
  voiceTransferUpdate(connected);
  replyReceiverUpdate(connected);
  petConfigUpdate(connected);
  const bool audioBusy = voiceRecording() || voiceReady() ||
      voiceTransferSending() || replyReceiverBusy() || voicePlayingReply();
  peerDistanceUpdate(audioBusy);
  peerExchangeUpdate(audioBusy);
  static uint32_t lastVoiceRevision = 0;
  static uint32_t lastReplyRevision = 0;
  static uint32_t lastPeerRevision = 0;
  static uint32_t lastPetRevision = 0;
  static uint32_t lastPetNotifyRevision = 0;
  static uint32_t lastStatusPeerRevision = 0;
  static uint32_t lastStatusStepCount = 0;
  static uint32_t lastDrawStepCount = 0;
  static unsigned long lastStatusRefresh = 0;
  static unsigned long lastStepStatusRefresh = 0;
  static unsigned long lastDraw = 0;
  const uint32_t steps = stepCounterCount();
  stepCounterUpdate(!audioBusy);
  if (petConfigRevision() != lastPetNotifyRevision) {
    lastPetNotifyRevision = petConfigRevision();
    const String json = statusJson();
    statusCharacteristic->setValue(json.c_str());
    if (connected) statusCharacteristic->notify();
  }
  if (peerDistanceRevision() != lastStatusPeerRevision &&
      millis() - lastStatusRefresh >= 250) {
    lastStatusPeerRevision = peerDistanceRevision();
    lastStatusRefresh = millis();
    statusCharacteristic->setValue(statusJson().c_str());
  }
  if (steps != lastStatusStepCount && !audioBusy &&
      millis() - lastStepStatusRefresh >= 2000) {
    lastStatusStepCount = steps;
    lastStepStatusRefresh = millis();
    statusCharacteristic->setValue(statusJson().c_str());
    if (connected) statusCharacteristic->notify();
  }
  if (connectionChanged) {
    connectionChanged = false;
    if (!connected) {
      voiceTransferReset();
      voiceCancel("Disconnected");
      replyReceiverReset();
      petConfigReset();
    }
    if (!playMode || modeChanged) drawScreen();
    lastVoiceRevision = voiceRevision();
    lastReplyRevision = replyReceiverRevision();
    lastPeerRevision = peerDistanceRevision();
    lastPetRevision = petConfigRevision();
    lastDrawStepCount = steps;
    lastDraw = millis();
  } else if (modeChanged ||
             ((voiceRevision() != lastVoiceRevision ||
               replyReceiverRevision() != lastReplyRevision) &&
              ((!voiceRecording() && !replyReceiverReceiving()) ||
               millis() - lastDraw >= 200)) ||
             ((petConfigRevision() != lastPetRevision ||
               peerDistanceRevision() != lastPeerRevision) &&
              millis() - lastDraw >= 250) ||
              (steps != lastDrawStepCount && millis() - lastDraw >= 250) ||
             (!audioBusy && millis() - lastDraw >= 1000)) {
    if (!playMode || modeChanged) drawScreen();
    lastVoiceRevision = voiceRevision();
    lastReplyRevision = replyReceiverRevision();
    lastPeerRevision = peerDistanceRevision();
    lastPetRevision = petConfigRevision();
    lastDrawStepCount = steps;
    lastDraw = millis();
  }
  delay(2);
}
