#pragma once

#include <Arduino.h>
#include <NimBLEDevice.h>

void peerExchangeBegin(NimBLEService* service, const String& deviceId);
void peerExchangeUpdate(bool audioBusy);
