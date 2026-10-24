#include "voice_recorder.h"

#include <Arduino.h>
#include <M5Unified.h>
#include <esp_heap_caps.h>

namespace {

constexpr uint32_t kSampleRate = 16000;
constexpr size_t kMaxSamples = kSampleRate * 5;
constexpr size_t kMinSamples = kSampleRate / 5;
constexpr size_t kBlockSamples = 512;

enum class State { Idle, Recording, Ready, Sending, PlayingReply, Error };
State state = State::Idle;
int16_t* pcm = nullptr;
uint8_t* encoded = nullptr;
size_t sampleCount = 0;
size_t queuedSamples = 0;
bool wasPressed = false;
bool replyStreamActive = false;
uint32_t revision = 0;
const char* message = "Hold A to record (max 5s)";

constexpr int kStep[89] = {
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
    143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
    1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660,
    4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493,
    10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385,
    24623, 27086, 29794, 32767};
constexpr int kIndexChange[8] = {-1, -1, -1, -1, 2, 4, 6, 8};

void setState(State next, const char* text) {
  state = next;
  message = text;
  ++revision;
}

void fail(const char* reason) {
  M5.Mic.end();
  queuedSamples = 0;
  sampleCount = 0;
  setState(State::Error, reason);
}

void encodeAdpcm() {
  int predictor = 0;
  int index = 0;
  for (size_t i = 0; i < sampleCount; ++i) {
    const int step = kStep[index];
    int difference = static_cast<int>(pcm[i]) - predictor;
    uint8_t nibble = 0;
    if (difference < 0) {
      nibble = 8;
      difference = -difference;
    }
    int change = step >> 3;
    if (difference >= step) {
      nibble |= 4;
      difference -= step;
      change += step;
    }
    if (difference >= (step >> 1)) {
      nibble |= 2;
      difference -= step >> 1;
      change += step >> 1;
    }
    if (difference >= (step >> 2)) {
      nibble |= 1;
      change += step >> 2;
    }
    predictor += (nibble & 8) ? -change : change;
    predictor = constrain(predictor, -32768, 32767);
    index = constrain(index + kIndexChange[nibble & 7], 0, 88);
    if ((i & 1) == 0) {
      encoded[i / 2] = nibble;
    } else {
      encoded[i / 2] |= nibble << 4;
    }
  }
}

void finishRecording() {
  M5.Mic.end();
  queuedSamples = 0;
  if (sampleCount < kMinSamples) {
    fail("Too short (hold A for 0.2s)");
    return;
  }
  if (encoded == nullptr) {
    encoded = static_cast<uint8_t*>(heap_caps_malloc(
        (kMaxSamples + 1) / 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  }
  if (encoded == nullptr) {
    fail("Audio memory unavailable");
    return;
  }
  encodeAdpcm();
  setState(State::Ready, "Compressed; waiting to send");
}

void startRecording() {
  sampleCount = 0;
  queuedSamples = 0;
  if (pcm == nullptr) {
    pcm = static_cast<int16_t*>(heap_caps_malloc(
        kMaxSamples * sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  }
  if (pcm == nullptr) {
    fail("Audio memory unavailable");
    return;
  }
  M5.Speaker.end();
  if (!M5.Mic.begin()) {
    fail("Microphone start failed");
    return;
  }
  setState(State::Recording, "Recording...");
}

}  // namespace

void voiceBegin() {
  auto config = M5.Mic.config();
  config.sample_rate = kSampleRate;
  config.over_sampling = 1;
  M5.Mic.config(config);
  M5.Speaker.end();
}

void voiceUpdate(bool canRecord) {
  const bool pressed = M5.BtnA.isPressed();
  const bool newPress = pressed && !wasPressed;
  wasPressed = pressed;

  if (state == State::PlayingReply) {
    if (!replyStreamActive && !M5.Speaker.isPlaying()) {
      M5.Speaker.end();
      setState(State::Idle, "Reply playback finished");
    }
    return;
  }

  if (!canRecord) {
    if (state == State::Recording) voiceCancel("Connection lost");
    return;
  }
  if (newPress && state != State::Recording && state != State::Sending) {
    startRecording();
  }
  if (state != State::Recording) return;
  if (!pressed) {
    // A pending block may also contain samples captured after release.
    finishRecording();
    return;
  }
  if (queuedSamples != 0) {
    if (M5.Mic.isRecording() != 0) return;
    sampleCount += queuedSamples;
    queuedSamples = 0;
    ++revision;
  }
  if (sampleCount >= kMaxSamples) {
    finishRecording();
    return;
  }
  const size_t count = min(kBlockSamples, kMaxSamples - sampleCount);
  if (!M5.Mic.record(pcm + sampleCount, count, kSampleRate)) {
    fail("Microphone recording failed");
    return;
  }
  queuedSamples = count;
}

void voiceCancel(const char* reason) {
  if (state == State::Recording) M5.Mic.end();
  if (state == State::PlayingReply) M5.Speaker.end();
  replyStreamActive = false;
  queuedSamples = 0;
  sampleCount = 0;
  setState(State::Idle, reason);
}

bool voiceRecording() { return state == State::Recording; }
bool voiceReady() { return state == State::Ready; }
bool voiceCanPlayReply() { return state == State::Idle || state == State::Error; }
bool voicePlayingReply() { return state == State::PlayingReply; }
bool voiceStartReplyStream() {
  if (!voiceCanPlayReply()) return false;
  M5.Mic.end();
  if (!M5.Speaker.begin()) return false;
  M5.Speaker.setVolume(128);
  replyStreamActive = true;
  setState(State::PlayingReply, "Playing reply...");
  return true;
}
bool voiceQueueReplySamples(const int16_t* samples, size_t count) {
  if (state != State::PlayingReply || !replyStreamActive ||
      samples == nullptr || count == 0 || M5.Speaker.isPlaying(0) >= 2) {
    return false;
  }
  return M5.Speaker.playRaw(samples, count, kSampleRate, false, 1, 0);
}
void voiceFinishReplyStream() { replyStreamActive = false; }
size_t voiceSampleCount() { return sampleCount; }
size_t voiceEncodedSize() { return (sampleCount + 1) / 2; }
const uint8_t* voiceEncodedData() { return encoded; }
float voiceDurationSeconds() { return static_cast<float>(sampleCount) / kSampleRate; }
void voiceTransferStarted() { setState(State::Sending, "Sending to Android..."); }
void voiceTransferFinished(bool success) {
  setState(success ? State::Idle : State::Error,
           success ? "Sent to Android" : "Send failed; record again");
}
const char* voiceMessage() { return message; }
uint32_t voiceRevision() { return revision; }
