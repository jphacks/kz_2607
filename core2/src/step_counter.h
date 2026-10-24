#pragma once

#include <stdint.h>

void stepCounterBegin();
void stepCounterUpdate(bool canPersist);
uint32_t stepCounterCount();
bool stepCounterAvailable();
