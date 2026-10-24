#pragma once

#include <NimBLEDevice.h>
#include <stdint.h>

void replyReceiverBegin(NimBLEService* service);
void replyReceiverUpdate(bool connected);
void replyReceiverReset();
bool replyReceiverBusy();
bool replyReceiverReceiving();
uint32_t replyReceiverRevision();
unsigned replyReceiverProgressPercent();
