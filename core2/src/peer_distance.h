#pragma once

#include <stdint.h>

struct PeerDistanceReading {
  char address[18];
  int rssi;
  float meters;
  uint32_t seenAt;
  uint8_t addressType;
};

void peerDistanceBegin();
void peerDistanceUpdate(bool audioBusy);
bool peerDistanceRead(PeerDistanceReading& reading);
bool peerDistanceReadAddress(const char* address, PeerDistanceReading& reading,
                             unsigned long maxAgeMs = 2000);
uint32_t peerDistanceRevision();
