#pragma once

#include <Arduino.h>
#include <NimBLEDevice.h>

void petConfigBegin(NimBLEService* service, NimBLECharacteristic* status,
                    const String& deviceId);
void petConfigUpdate(bool connected);
void petConfigReset();
void petConfigSetAndroidConnection(uint16_t handle);
const String& petConfigId();
uint32_t petConfigRevision();
bool petConfigCreateExchange(const String& transactionId,
                             const String& peerDeviceId,
                             const String& givenPetId,
                             const String& gotPetId, float distanceMeters);
bool petConfigExchangePending();
const String& petConfigExchangeTransactionId();
const String& petConfigExchangePeerId();
const String& petConfigExchangeGivenId();
const String& petConfigExchangeGotId();
uint32_t petConfigExchangeSequence();
const char* petConfigExchangeStatus();
