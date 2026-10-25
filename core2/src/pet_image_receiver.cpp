#include "pet_image_receiver.h"

#include <Arduino.h>
#include <M5Unified.h>
#include <esp_heap_caps.h>

#include <cstring>
#include <new>
#include <string>

#include "pet_config.h"
#include "reply_receiver.h"
#include "voice_recorder.h"
#include "voice_transfer.h"

namespace {

constexpr char kDataUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000009";
constexpr char kAckUuid[] = "7f5a0001-7b7d-4f3b-9d01-00000000000a";
constexpr size_t kMaxImageBytes = 128 * 1024;
constexpr size_t kMaxFrameBytes = 244;
constexpr size_t kQueueSize = 16;
constexpr unsigned long kReceiveTimeoutMs = 5000;

enum class State { Idle, Receiving };
State state = State::Idle;
NimBLECharacteristic* ackCharacteristic = nullptr;
volatile uint16_t androidConnectionHandle = UINT16_MAX;
portMUX_TYPE queueMux = portMUX_INITIALIZER_UNLOCKED;
struct Frame {
  uint16_t size;
  uint8_t bytes[kMaxFrameBytes];
};
Frame queue[kQueueSize];
size_t queueHead = 0;
size_t queueCount = 0;

uint8_t* incoming = nullptr;
M5Canvas* imageCanvas = nullptr;
uint16_t imageWidth = 0;
uint16_t imageHeight = 0;
String imagePetId;
uint32_t revision = 0;

uint8_t session = 0;
uint16_t width = 0;
uint16_t height = 0;
uint8_t chunkSize = 0;
uint32_t expectedSize = 0;
uint32_t expectedCrc = 0;
uint32_t petIdCrc = 0;
uint32_t received = 0;
uint16_t lastSequence = 0;
unsigned long lastPacketAt = 0;
bool completed = false;
uint8_t completedSession = 0;
uint16_t completedEndSequence = 0;

uint16_t read16(const uint8_t* p) {
  return static_cast<uint16_t>(p[0]) | static_cast<uint16_t>(p[1]) << 8;
}

uint32_t read32(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) | static_cast<uint32_t>(p[1]) << 8 |
         static_cast<uint32_t>(p[2]) << 16 | static_cast<uint32_t>(p[3]) << 24;
}

uint32_t readBig32(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) << 24 |
         static_cast<uint32_t>(p[1]) << 16 |
         static_cast<uint32_t>(p[2]) << 8 | static_cast<uint32_t>(p[3]);
}

uint32_t crc32(const uint8_t* data, size_t size) {
  uint32_t crc = 0xffffffff;
  for (size_t i = 0; i < size; ++i) {
    crc ^= data[i];
    for (int bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
  }
  return crc ^ 0xffffffff;
}

uint32_t currentPetIdCrc() {
  const String& petId = petConfigId();
  return crc32(reinterpret_cast<const uint8_t*>(petId.c_str()), petId.length());
}

bool audioBusy() {
  return voiceRecording() || voiceReady() || voiceTransferSending() ||
         replyReceiverBusy() || voicePlayingReply() ||
         petConfigExchangePending();
}

void sendAck(uint8_t type, uint8_t id, uint16_t sequence) {
  if (!ackCharacteristic || androidConnectionHandle == UINT16_MAX) return;
  const uint8_t frame[] = {type, id, static_cast<uint8_t>(sequence),
                           static_cast<uint8_t>(sequence >> 8)};
  ackCharacteristic->notify(frame, sizeof(frame));
}

void sendError(uint8_t id, uint8_t code) {
  sendAck(4, id, code);
}

void stopReceiving() {
  free(incoming);
  incoming = nullptr;
  state = State::Idle;
  received = 0;
  lastSequence = 0;
}

bool popFrame(Frame& frame) {
  bool found = false;
  portENTER_CRITICAL(&queueMux);
  if (queueCount != 0) {
    frame = queue[queueHead];
    queueHead = (queueHead + 1) % kQueueSize;
    --queueCount;
    found = true;
  }
  portEXIT_CRITICAL(&queueMux);
  return found;
}

class DataCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo& info) override {
    if (info.getConnHandle() != androidConnectionHandle) return;
    const std::string value = characteristic->getValue();
    if (value.size() < 2 || value.size() > kMaxFrameBytes) return;
    portENTER_CRITICAL(&queueMux);
    if (queueCount < kQueueSize) {
      Frame& frame = queue[(queueHead + queueCount) % kQueueSize];
      frame.size = value.size();
      memcpy(frame.bytes, value.data(), value.size());
      ++queueCount;
    }
    portEXIT_CRITICAL(&queueMux);
  }
};

void handleStart(const Frame& frame) {
  const uint8_t* p = frame.bytes;
  const uint8_t id = p[1];
  if (frame.size != 20 || p[6] != 1 || read16(p + 2) == 0 ||
      read16(p + 2) > 320 || read16(p + 4) == 0 || read16(p + 4) > 240 ||
      p[7] == 0 || p[7] > 240 || read32(p + 8) == 0 ||
      read32(p + 8) > kMaxImageBytes ||
      (read32(p + 8) + p[7] - 1) / p[7] >= UINT16_MAX ||
      petConfigId().isEmpty() || read32(p + 16) != currentPetIdCrc()) {
    sendError(id, 1);
    return;
  }
  if (state == State::Receiving && session == id) {
    sendAck(2, id, 0);
    return;
  }
  if (audioBusy()) {
    sendError(id, 2);
    return;
  }
  stopReceiving();
  completed = false;
  incoming = static_cast<uint8_t*>(heap_caps_malloc(
      read32(p + 8), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!incoming) {
    sendError(id, 3);
    return;
  }
  session = id;
  width = read16(p + 2);
  height = read16(p + 4);
  chunkSize = p[7];
  expectedSize = read32(p + 8);
  expectedCrc = read32(p + 12);
  petIdCrc = read32(p + 16);
  lastPacketAt = millis();
  state = State::Receiving;
  sendAck(2, id, 0);
}

void handleData(const Frame& frame) {
  if (frame.size < 5 || state != State::Receiving ||
      frame.bytes[1] != session) return;
  const uint16_t sequence = read16(frame.bytes + 2);
  lastPacketAt = millis();
  if (audioBusy() || currentPetIdCrc() != petIdCrc) {
    sendError(session, 2);
    stopReceiving();
    return;
  }
  if (sequence <= lastSequence || sequence != lastSequence + 1) {
    sendAck(2, session, lastSequence);
    return;
  }
  const size_t payloadSize = frame.size - 4;
  const size_t remaining = expectedSize - received;
  const size_t needed = remaining < chunkSize ? remaining : chunkSize;
  if (payloadSize != needed) {
    sendError(session, 1);
    stopReceiving();
    return;
  }
  memcpy(incoming + received, frame.bytes + 4, payloadSize);
  received += payloadSize;
  lastSequence = sequence;
  if (sequence % 8 == 0 || received == expectedSize) {
    sendAck(2, session, sequence);
  }
}

void handleEnd(const Frame& frame) {
  if (frame.size != 4) return;
  const uint8_t id = frame.bytes[1];
  const uint16_t sequence = read16(frame.bytes + 2);
  if (completed && id == completedSession &&
      sequence == completedEndSequence) {
    sendAck(2, id, sequence);
    return;
  }
  if (state != State::Receiving || id != session) return;
  if (sequence != lastSequence + 1 || received != expectedSize ||
      currentPetIdCrc() != petIdCrc || audioBusy()) {
    Serial.printf("Pet image END rejected: seq=%u expected=%u bytes=%lu/%lu pet=%u busy=%u\n",
                  sequence, lastSequence + 1,
                  static_cast<unsigned long>(received),
                  static_cast<unsigned long>(expectedSize),
                  currentPetIdCrc() == petIdCrc, audioBusy());
    sendError(id, 4);
    stopReceiving();
    return;
  }
  const uint8_t pngSignature[] = {137, 80, 78, 71, 13, 10, 26, 10};
  if (expectedSize < 24 || memcmp(incoming, pngSignature, 8) != 0 ||
      readBig32(incoming + 8) != 13 || memcmp(incoming + 12, "IHDR", 4) != 0 ||
      readBig32(incoming + 16) != width ||
      readBig32(incoming + 20) != height ||
      crc32(incoming, expectedSize) != expectedCrc) {
    Serial.printf("Pet image PNG validation failed: IHDR=%lu size=%lux%lu expected=%ux%u crc=%08lx expected=%08lx\n",
                  static_cast<unsigned long>(expectedSize >= 12 ? readBig32(incoming + 8) : 0),
                  static_cast<unsigned long>(expectedSize >= 20 ? readBig32(incoming + 16) : 0),
                  static_cast<unsigned long>(expectedSize >= 24 ? readBig32(incoming + 20) : 0),
                  width, height,
                  static_cast<unsigned long>(crc32(incoming, expectedSize)),
                  static_cast<unsigned long>(expectedCrc));
    sendError(id, 4);
    stopReceiving();
    return;
  }
  // Decode off-screen so an invalid PNG never replaces the current pet.
  M5Canvas* canvas = new (std::nothrow) M5Canvas(&M5.Display);
  if (!canvas) {
    sendError(id, 3);
    stopReceiving();
    return;
  }
  canvas->setColorDepth(16);
  if (!canvas->createSprite(width, height)) {
    delete canvas;
    sendError(id, 3);
    stopReceiving();
    return;
  }
  canvas->fillSprite(TFT_BLACK);
  if (!canvas->drawPng(incoming, expectedSize, 0, 0)) {
    Serial.println("Pet image PNG decode failed");
    delete canvas;
    sendError(id, 4);
    stopReceiving();
    return;
  }
  delete imageCanvas;
  imageCanvas = canvas;
  imageWidth = width;
  imageHeight = height;
  imagePetId = petConfigId();
  stopReceiving();
  completed = true;
  completedSession = id;
  completedEndSequence = sequence;
  ++revision;
  sendAck(2, id, sequence);
  Serial.printf("Pet image received: %lu bytes, %ux%u\n",
                static_cast<unsigned long>(expectedSize), imageWidth, imageHeight);
}

}  // namespace

void petImageReceiverBegin(NimBLEService* service) {
  NimBLECharacteristic* data = service->createCharacteristic(
      kDataUuid, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  data->setCallbacks(new DataCallbacks());
  ackCharacteristic = service->createCharacteristic(kAckUuid, NIMBLE_PROPERTY::NOTIFY);
}

void petImageReceiverSetAndroidConnection(uint16_t handle) {
  androidConnectionHandle = handle;
}

void petImageReceiverUpdate(bool connected) {
  if (!connected) return;
  if (state == State::Receiving && millis() - lastPacketAt > kReceiveTimeoutMs) {
    stopReceiving();
  }
  Frame frame;
  while (popFrame(frame)) {
    switch (frame.bytes[0]) {
      case 1: handleStart(frame); break;
      case 2: handleData(frame); break;
      case 3: handleEnd(frame); break;
      default: break;
    }
  }
}

void petImageReceiverResetConnection() {
  portENTER_CRITICAL(&queueMux);
  queueHead = 0;
  queueCount = 0;
  portEXIT_CRITICAL(&queueMux);
  stopReceiving();
  completed = false;
}

void petImageReceiverClear() {
  petImageReceiverResetConnection();
  delete imageCanvas;
  imageCanvas = nullptr;
  imagePetId = "";
  ++revision;
}

bool petImageReceiverBusy() { return state == State::Receiving; }

bool petImageReceiverDraw() {
  if (!imageCanvas || imagePetId != petConfigId()) return false;
  const int x = (M5.Display.width() - imageWidth) / 2;
  const int y = (M5.Display.height() - imageHeight) / 2;
  imageCanvas->pushSprite(x, y);
  return true;
}

uint32_t petImageReceiverRevision() { return revision; }
