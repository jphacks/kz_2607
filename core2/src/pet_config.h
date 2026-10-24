#pragma once

#include <Arduino.h>
#include <NimBLEDevice.h>

void petConfigBegin(NimBLEService* service, NimBLECharacteristic* status,
                    const String& deviceId);
void petConfigUpdate(bool connected);
void petConfigReset();
const String& petConfigId();
uint32_t petConfigRevision();
