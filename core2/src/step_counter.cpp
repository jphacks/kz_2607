#include "step_counter.h"

#include <Arduino.h>
#include <M5Unified.h>
#include <Preferences.h>
#include <math.h>

namespace {

constexpr uint32_t kSampleMs = 25;
constexpr uint32_t kMinStepIntervalMs = 250;
constexpr uint32_t kMaxStepIntervalMs = 1800;
constexpr uint32_t kSaveAfterIdleMs = 10000;
constexpr uint32_t kSaveIntervalMs = 60000;
constexpr uint32_t kSaveRetryMs = 5000;
constexpr uint32_t kSaveEverySteps = 50;
constexpr float kMinimumPeakG = 0.055f;
constexpr float kMaximumPeakG = 2.5f;

Preferences preferences;
portMUX_TYPE countMux = portMUX_INITIALIZER_UNLOCKED;
uint32_t stepCount = 0;
bool sensorAvailable = false;
bool storageAvailable = false;
uint32_t savedCount = 0;
uint32_t observedCount = 0;
uint32_t lastStepAt = 0;
uint32_t lastSavedAt = 0;
uint32_t lastSaveAttemptAt = 0;

class StepDetector {
 public:
  uint8_t update(float ax, float ay, float az, uint32_t now) {
    const float magnitude = sqrtf(ax * ax + ay * ay + az * az);
    if (!isfinite(magnitude) || magnitude < 0.2f || magnitude > 4.0f)
      return 0;
    if (!initialized_) {
      gravity_ = magnitude;
      initialized_ = true;
      return 0;
    }

    // Magnitude does not depend on the Core2's orientation inside a pocket.
    gravity_ += 0.025f * (magnitude - gravity_);
    motion_ += 0.35f * ((magnitude - gravity_) - motion_);
    if (!aboveThreshold_) {
      noise_ += 0.02f * (fabsf(motion_) - noise_);
    }
    const float threshold = fmaxf(kMinimumPeakG, noise_ * 2.2f);
    if (!aboveThreshold_) {
      if (motion_ > threshold) {
        aboveThreshold_ = true;
        peak_ = motion_;
        peakAt_ = now;
      }
      return 0;
    }
    if (motion_ > peak_) {
      peak_ = motion_;
      peakAt_ = now;
    }
    if (motion_ >= threshold * 0.45f) return 0;
    aboveThreshold_ = false;
    if (peak_ > kMaximumPeakG) {
      hasPreviousPeak_ = false;
      walking_ = false;
      return 0;
    }

    if (hasPreviousPeak_) {
      const uint32_t interval = peakAt_ - previousPeakAt_;
      if (interval < kMinStepIntervalMs) return 0;
      if (interval <= kMaxStepIntervalMs) {
        previousPeakAt_ = peakAt_;
        if (!walking_) {
          walking_ = true;
          return 2;  // Count the first and second rhythmic peaks together.
        }
        return 1;
      }
    }
    previousPeakAt_ = peakAt_;
    hasPreviousPeak_ = true;
    walking_ = false;
    return 0;
  }

 private:
  bool initialized_ = false;
  bool aboveThreshold_ = false;
  bool hasPreviousPeak_ = false;
  bool walking_ = false;
  float gravity_ = 1.0f;
  float motion_ = 0.0f;
  float noise_ = 0.0f;
  float peak_ = 0.0f;
  uint32_t peakAt_ = 0;
  uint32_t previousPeakAt_ = 0;
};

void sampleTask(void*) {
  StepDetector detector;
  TickType_t nextSample = xTaskGetTickCount();
  for (;;) {
    vTaskDelayUntil(&nextSample, pdMS_TO_TICKS(kSampleMs));
    if (!(M5.Imu.update() & m5::IMU_Class::sensor_mask_accel)) continue;
    const auto& data = M5.Imu.getImuData();
    const uint8_t steps = detector.update(data.accel.x, data.accel.y,
                                          data.accel.z, millis());
    if (steps == 0) continue;
    portENTER_CRITICAL(&countMux);
    stepCount = stepCount > UINT32_MAX - steps ? UINT32_MAX : stepCount + steps;
    portEXIT_CRITICAL(&countMux);
  }
}

}  // namespace

void stepCounterBegin() {
  storageAvailable = preferences.begin("steps", false);
  if (storageAvailable) stepCount = preferences.getUInt("total", 0);
  savedCount = observedCount = stepCount;
  lastSavedAt = lastStepAt = millis();
  if (!M5.Imu.isEnabled()) {
    Serial.println("STEPS IMU unavailable");
    return;
  }
  sensorAvailable = xTaskCreatePinnedToCore(sampleTask, "stepCounter", 4096,
                                            nullptr, 1, nullptr, 1) == pdPASS;
  Serial.printf("STEPS IMU %s, count=%lu\n",
                sensorAvailable ? "ready" : "task failed",
                static_cast<unsigned long>(stepCount));
}

void stepCounterUpdate(bool canPersist) {
  const uint32_t now = millis();
  const uint32_t current = stepCounterCount();
  if (current != observedCount) {
    observedCount = current;
    lastStepAt = now;
  }
  if (!storageAvailable || !canPersist || current == savedCount ||
      now - lastSaveAttemptAt < kSaveRetryMs ||
      (current - savedCount < kSaveEverySteps &&
       now - lastSavedAt < kSaveIntervalMs &&
       now - lastStepAt < kSaveAfterIdleMs)) return;
  lastSaveAttemptAt = now;
  if (preferences.putUInt("total", current) == sizeof(uint32_t)) {
    savedCount = current;
    lastSavedAt = now;
  }
}

uint32_t stepCounterCount() {
  portENTER_CRITICAL(&countMux);
  const uint32_t current = stepCount;
  portEXIT_CRITICAL(&countMux);
  return current;
}

bool stepCounterAvailable() { return sensorAvailable; }
