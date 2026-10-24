#include "peer_distance.h"

#include <Arduino.h>
#include <NimBLEDevice.h>
#include <math.h>
#include <string.h>

namespace {

constexpr char kServiceUuid[] = "7f5a0001-7b7d-4f3b-9d01-000000000001";
constexpr size_t kPeerCapacity = 4;
constexpr unsigned long kPeerTimeoutMs = 2000;
constexpr int kRssiAtOneMeter = -59;
constexpr float kPathLoss = 2.0f;

struct Peer {
  char address[18] = {};
  int rssi = -127;
  unsigned long lastSeen = 0;
  bool valid = false;
};

Peer peers[kPeerCapacity];
portMUX_TYPE peersMux = portMUX_INITIALIZER_UNLOCKED;
uint32_t revision = 0;
std::string ownAddress;
unsigned long lastScanAttempt = 0;

class PeerScanCallbacks : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* device) override {
    if (!device->isAdvertisingService(NimBLEUUID(kServiceUuid))) return;
    const std::string address = device->getAddress().toString();
    if (address == ownAddress || address.size() != 17) return;
    const int rssi = device->getRSSI();
    if (rssi >= 0 || rssi <= -127) return;
    const unsigned long now = millis();

    portENTER_CRITICAL(&peersMux);
    size_t slot = kPeerCapacity;
    size_t replace = 0;
    for (size_t i = 0; i < kPeerCapacity; ++i) {
      if (peers[i].valid && strcmp(peers[i].address, address.c_str()) == 0) {
        slot = i;
        break;
      }
      if (!peers[i].valid || now - peers[i].lastSeen > kPeerTimeoutMs) {
        replace = i;
      } else if (peers[replace].valid &&
                 now - peers[replace].lastSeen <= kPeerTimeoutMs &&
                 peers[i].rssi < peers[replace].rssi) {
        replace = i;
      }
    }
    if (slot == kPeerCapacity) slot = replace;
    Peer& peer = peers[slot];
    const bool samePeer = peer.valid &&
        now - peer.lastSeen <= kPeerTimeoutMs &&
        strcmp(peer.address, address.c_str()) == 0;
    // Favor recent measurements so the displayed distance follows movement.
    peer.rssi = samePeer ? (peer.rssi + rssi * 2) / 3 : rssi;
    memcpy(peer.address, address.c_str(), 18);
    peer.lastSeen = now;
    peer.valid = true;
    ++revision;
    portEXIT_CRITICAL(&peersMux);
  }
};

PeerScanCallbacks callbacks;

}  // namespace

void peerDistanceBegin() {
  ownAddress = NimBLEDevice::getAddress().toString();
  NimBLEScan* scan = NimBLEDevice::getScan();
  scan->setScanCallbacks(&callbacks, true);
  scan->setActiveScan(false);
  scan->setInterval(100);
  scan->setWindow(70);
  scan->setMaxResults(0);
}

void peerDistanceUpdate(bool audioBusy) {
  NimBLEScan* scan = NimBLEDevice::getScan();
  if (audioBusy) {
    if (scan->isScanning()) scan->stop();
    return;
  }
  const unsigned long now = millis();
  if (!scan->isScanning() && now - lastScanAttempt >= 500) {
    lastScanAttempt = now;
    scan->start(0, false, false);
  }
}

bool peerDistanceRead(PeerDistanceReading& reading) {
  Peer closest;
  bool found = false;
  const unsigned long now = millis();
  portENTER_CRITICAL(&peersMux);
  for (const Peer& peer : peers) {
    if (peer.valid && now - peer.lastSeen <= kPeerTimeoutMs &&
        (!found || peer.rssi > closest.rssi)) {
      closest = peer;
      found = true;
    }
  }
  portEXIT_CRITICAL(&peersMux);
  if (!found) return false;
  memcpy(reading.address, closest.address, sizeof(reading.address));
  reading.rssi = closest.rssi;
  reading.meters = powf(10.0f,
      (kRssiAtOneMeter - reading.rssi) / (10.0f * kPathLoss));
  return true;
}

uint32_t peerDistanceRevision() {
  portENTER_CRITICAL(&peersMux);
  const uint32_t current = revision;
  portEXIT_CRITICAL(&peersMux);
  return current;
}
