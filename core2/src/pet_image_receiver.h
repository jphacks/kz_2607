#pragma once

#include <NimBLEDevice.h>
#include <stdint.h>

void petImageReceiverBegin(NimBLEService* service);
void petImageReceiverSetAndroidConnection(uint16_t handle);
void petImageReceiverUpdate(bool connected);
void petImageReceiverResetConnection();
void petImageReceiverClear();
bool petImageReceiverBusy();
bool petImageReceiverDraw();
uint32_t petImageReceiverRevision();
