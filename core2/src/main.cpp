#include <Arduino.h>
#include <M5Unified.h>
#include <NimBLEDevice.h>

#include "voice_recorder.h"
#include "voice_transfer.h"
#include "reply_receiver.h"
#include "peer_distance.h"

namespace {

constexpr char kDeviceName[] = "M5StackCore2";
constexpr char kServiceUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000001";
constexpr char kStatusUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000002";

volatile bool connected = false;
volatile bool connectionChanged = true;
String macAddress;
String deviceId;

String statusJson() {
  // Keep the basic fields understood by the demo Android status parser.
  return "{\"id\":\"M5-" + deviceId + "\",\"mac\":\"" + macAddress +
         "\",\"peerId\":\"\",\"distance\":0,\"petId\":\"\"}";
}

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer*, NimBLEConnInfo&) override {
    connected = true;
    connectionChanged = true;
    // Keep the Core2 visible to another Core2 while Android is connected.
    NimBLEDevice::startAdvertising();
  }

  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int) override {
    connected = false;
    connectionChanged = true;
    voiceTransferClearConfiguration();
    NimBLEDevice::startAdvertising();
  }
};

void drawScreen() {
  M5.Display.fillScreen(TFT_NAVY);
  M5.Display.setTextColor(TFT_WHITE, TFT_NAVY);
  M5.Display.setTextSize(2);
  M5.Display.setCursor(16, 20);
  M5.Display.print("Core2 BLE");

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
        peer.meters <= 1.5f ? TFT_YELLOW : TFT_WHITE, TFT_NAVY);
    M5.Display.setCursor(16, 124);
    if (peer.meters > 20.0f) {
      M5.Display.print("DIST: >20 m");
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

  M5.Display.drawFastHLine(16, 188, M5.Display.width() - 32, TFT_WHITE);
  M5.Display.setCursor(16, 198);
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
  M5.Display.setCursor(16, 220);
  M5.Display.print("Hold A to talk");
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
  NimBLECharacteristic* status = service->createCharacteristic(
      kStatusUuid, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
  status->setValue(statusJson().c_str());
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
  startBle();
  drawScreen();
}

void loop() {
  M5.update();
  voiceUpdate(connected && voiceTransferConfigured() && !replyReceiverBusy());
  voiceTransferUpdate(connected);
  replyReceiverUpdate(connected);
  const bool audioBusy = voiceRecording() || voiceReady() ||
      voiceTransferSending() || replyReceiverBusy() || voicePlayingReply();
  peerDistanceUpdate(audioBusy);
  static uint32_t lastVoiceRevision = 0;
  static uint32_t lastReplyRevision = 0;
  static uint32_t lastPeerRevision = 0;
  static unsigned long lastDraw = 0;
  if (connectionChanged) {
    connectionChanged = false;
    if (!connected) {
      voiceTransferReset();
      voiceCancel("Disconnected");
      replyReceiverReset();
    }
    drawScreen();
    lastVoiceRevision = voiceRevision();
    lastReplyRevision = replyReceiverRevision();
    lastPeerRevision = peerDistanceRevision();
    lastDraw = millis();
  } else if (((voiceRevision() != lastVoiceRevision ||
               replyReceiverRevision() != lastReplyRevision) &&
              ((!voiceRecording() && !replyReceiverReceiving()) ||
               millis() - lastDraw >= 200)) ||
             (peerDistanceRevision() != lastPeerRevision &&
              millis() - lastDraw >= 250) ||
             (!audioBusy && millis() - lastDraw >= 1000)) {
    drawScreen();
    lastVoiceRevision = voiceRevision();
    lastReplyRevision = replyReceiverRevision();
    lastPeerRevision = peerDistanceRevision();
    lastDraw = millis();
  }
  delay(2);
}
