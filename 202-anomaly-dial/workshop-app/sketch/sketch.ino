#include <Arduino_Modulino.h>
#include <Arduino_RouterBridge.h>

ModulinoKnob knob;
ModulinoPixels pixels;
ModulinoVibro vibro;

const unsigned long SAMPLE_PERIOD_US = 20000;  // 50 Hz hardware sampling.
volatile int latestKnob = 0;
volatile int latestPressed = 0;
unsigned long lastSampleAt = 0;

enum DisplayMode {
  MODE_LIVE = 0,
  MODE_TRAIN_NORMAL = 1,
  MODE_RECORDING = 2,
  MODE_TRAINING_MODEL = 3,
  MODE_RETRY = 4,
  MODE_ERROR = 5
};

int read_knob() {
  return latestKnob;
}

int read_pressed() {
  return latestPressed;
}

void fill_pixels(uint8_t red, uint8_t green, uint8_t blue, int litPixels) {
  litPixels = constrain(litPixels, 0, 8);
  pixels.clear();
  for (int i = 0; i < litPixels; i++) {
    pixels.set(i, red, green, blue, 25);
  }
  pixels.show();
}

void show_mode(int mode, int progress) {
  switch (mode) {
    case MODE_LIVE:
      fill_pixels(0, 120, 220, progress);
      break;
    case MODE_TRAIN_NORMAL:
      fill_pixels(220, 40, 120, max(1, progress));
      break;
    case MODE_RECORDING:
      fill_pixels(220, 220, 220, 8);
      break;
    case MODE_TRAINING_MODEL:
      fill_pixels(120, 70, 220, 8);
      break;
    case MODE_RETRY:
      fill_pixels(230, 150, 0, progress);
      break;
    default:
      fill_pixels(220, 0, 0, 8);
      break;
  }
}

void show_result(int anomalous, int level) {
  level = constrain(level, 0, 100);
  int litPixels = max(1, (level * 8 + 99) / 100);
  if (anomalous) {
    fill_pixels(220, 0, 0, litPixels);
    vibro.on(320);
  } else {
    fill_pixels(40, 200, 80, litPixels);
  }
}

void pulse_feedback(int kind) {
  switch (kind) {
    case 0:  // Ready.
      vibro.on(180);
      break;
    case 1:  // Training example accepted.
      vibro.on(120);
      break;
    case 2:  // Training finished.
      vibro.on(400);
      break;
    default:  // Retry or error.
      vibro.on(80);
      break;
  }
}

void setup() {
  Modulino.begin();
  knob.begin();
  pixels.begin();
  vibro.begin();

  knob.set(0);
  latestKnob = knob.get();
  latestPressed = knob.isPressed() ? 1 : 0;
  lastSampleAt = micros();
  show_mode(MODE_LIVE, 8);
  pulse_feedback(0);

  Bridge.begin();
  Bridge.provide("read_knob", read_knob);
  Bridge.provide("read_pressed", read_pressed);
  Bridge.provide_safe("show_mode", show_mode);
  Bridge.provide_safe("show_result", show_result);
  Bridge.provide_safe("pulse_feedback", pulse_feedback);
}

void loop() {
  unsigned long now = micros();
  if (now - lastSampleAt >= SAMPLE_PERIOD_US) {
    lastSampleAt = now;
    latestKnob = knob.get();
    latestPressed = knob.isPressed() ? 1 : 0;
  }
}
