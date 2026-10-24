#pragma once

#include <NimBLEDevice.h>

void voiceTransferBegin(NimBLEService* service);
void voiceTransferUpdate(bool connected);
void voiceTransferReset();
void voiceTransferClearConfiguration();
bool voiceTransferConfigured();
