#include <Arduino.h>
#include <M5Unified.h>
#include <NimBLEDevice.h>

namespace {

constexpr char kDeviceName[] = "M5StackCore2-1";
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
  }

  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int) override {
    connected = false;
    connectionChanged = true;
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
  M5.Display.setCursor(16, 135);
  M5.Display.printf("Name: %s", kDeviceName);
  M5.Display.setCursor(16, 155);
  M5.Display.printf("MAC: %s", macAddress.c_str());
  M5.Display.setCursor(16, 175);
  M5.Display.printf("ID: M5-%s", deviceId.c_str());
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
  server->start();

  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(kServiceUuid);
  advertising->enableScanResponse(true);
  advertising->setName(kDeviceName);
  advertising->start();
}

}  // namespace

void setup() {
  M5.begin(M5.config());
  startBle();
  drawScreen();
}

void loop() {
  M5.update();
  if (connectionChanged) {
    connectionChanged = false;
    drawScreen();
  }
  delay(20);
}
