#pragma once

#include <stdint.h>

struct PeerDistanceReading {
  char address[18];
  int rssi;
  float meters;
};

void peerDistanceBegin();
void peerDistanceUpdate(bool audioBusy);
bool peerDistanceRead(PeerDistanceReading& reading);
uint32_t peerDistanceRevision();
