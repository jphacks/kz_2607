#pragma once

#include <stddef.h>
#include <stdint.h>

void voiceBegin();
void voiceUpdate(bool canRecord);
void voiceCancel(const char* reason);
bool voiceRecording();
bool voiceReady();
bool voiceCanPlayReply();
bool voicePlayingReply();
bool voiceStartReplyStream();
bool voiceQueueReplySamples(const int16_t* samples, size_t count);
void voiceFinishReplyStream();
void voiceAdjustVolume(int delta);
uint8_t voiceVolume();
size_t voiceSampleCount();
size_t voiceEncodedSize();
const uint8_t* voiceEncodedData();
float voiceDurationSeconds();
void voiceTransferStarted();
void voiceTransferFinished(bool success);
const char* voiceMessage();
uint32_t voiceRevision();
