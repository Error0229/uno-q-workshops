from arduino.app_utils import App, Bridge

import time
from pathlib import Path

from anomaly_model import ANOMALY_THRESHOLD, extract_features, load, predict, save, train


SAMPLE_INTERVAL_SECONDS = 0.05
MOTION_END_SECONDS = 0.30
MAX_MOTION_SECONDS = 4.0
START_TIMEOUT_SECONDS = 5.0
TRAINING_EXAMPLES = 10
HOLD_TO_RETRAIN_SECONDS = 3.0

APP_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = APP_ROOT / "data" / "anomaly_model.json"

model = None
mode = "starting"
initialized = False
training_examples = []
capture_samples = []
capture_armed_at = None
last_motion_at = None
last_sample = None
last_pressed = 0
pressed_at = None
ignore_next_release = False


def reset_capture():
    global capture_samples, last_motion_at, capture_armed_at
    capture_samples = []
    last_motion_at = None
    capture_armed_at = None


def show_training_prompt():
    completed = len(training_examples)
    Bridge.call("show_mode", 1, round(completed * 8 / TRAINING_EXAMPLES))
    print(
        f"TRAIN normal: example {completed + 1}/{TRAINING_EXAMPLES}. "
        "Press and release the knob, then turn smoothly for about one second and stop."
    )


def begin_training(clear_saved_model=False):
    global model, mode, training_examples
    if clear_saved_model:
        try:
            MODEL_PATH.unlink(missing_ok=True)
        except OSError as error:
            print(f"Could not erase saved model: {error}. Release and hold again to retry.")
            Bridge.call("show_mode", 5, 8)
            return
    model = None
    training_examples = []
    reset_capture()
    mode = "training_ready"
    print("\nRecord ten examples of normal turning. Use similar speeds and durations.")
    show_training_prompt()


def print_live_help():
    print("\nLIVE: turn normally, then try faster, longer, or back-and-forth movements.")
    print(f"Green = normal; red + vibration = anomaly (score > {ANOMALY_THRESHOLD}).")
    print("Hold the knob for three seconds to erase the model and retrain.")


def load_or_train():
    global model, mode
    try:
        model = load(MODEL_PATH)
    except (OSError, ValueError) as error:
        print(f"Ignoring saved model: {error}")
        model = None
    if model is None:
        begin_training()
    else:
        mode = "live"
        Bridge.call("show_mode", 0, 8)
        print(f"Loaded anomaly model from {MODEL_PATH}")
        print_live_help()


def finish_capture():
    global mode, model
    samples = capture_samples
    reset_capture()
    try:
        features = extract_features(samples)
    except ValueError as error:
        print(f"Ignored movement: {error}")
        if mode == "capturing":
            Bridge.call("show_mode", 4, 3)
            Bridge.call("pulse_feedback", 3)
            time.sleep(0.5)
            mode = "training_ready"
            show_training_prompt()
        return

    if mode == "capturing":
        training_examples.append(features)
        print(f"Accepted normal example {len(training_examples)}/{TRAINING_EXAMPLES}.")
        Bridge.call("pulse_feedback", 1)
        if len(training_examples) < TRAINING_EXAMPLES:
            mode = "training_ready"
            show_training_prompt()
            return

        Bridge.call("show_mode", 3, 8)
        model = train(training_examples)
        try:
            save(model, MODEL_PATH)
            print(f"Model saved to {MODEL_PATH}")
        except OSError as error:
            print(f"Model is active but could not be saved: {error}. Restarting will retrain.")
        mode = "live"
        Bridge.call("show_mode", 0, 8)
        Bridge.call("pulse_feedback", 2)
        print_live_help()
    else:
        result = predict(model, features)
        status = "ANOMALY" if result["anomalous"] else "NORMAL"
        print(
            f"{status} score={result['score']:.2f}, largest deviation={result['feature']}; "
            f"duration={features[0]:.2f}s, mean={features[1]:.1f} steps/s, "
            f"peak={features[2]:.1f} steps/s, reversals={features[3]:.0f}"
        )
        level = min(100, round(result["score"] / (2 * ANOMALY_THRESHOLD) * 100))
        Bridge.call("show_result", int(result["anomalous"]), level)


def update_capture(sample):
    global capture_samples, last_motion_at
    now, position = sample
    moved = position != last_sample[1]
    if not capture_samples:
        if moved:
            capture_samples = [last_sample, sample]
            last_motion_at = now
        elif mode == "capturing" and now - capture_armed_at >= START_TIMEOUT_SECONDS:
            finish_capture()
        return

    capture_samples.append(sample)
    if moved:
        last_motion_at = now
    stopped = now - last_motion_at >= MOTION_END_SECONDS
    timed_out = now - capture_samples[0][0] >= MAX_MOTION_SECONDS
    if stopped or timed_out:
        finish_capture()


def loop():
    global initialized, mode, last_sample, last_pressed, pressed_at
    global ignore_next_release, capture_armed_at
    if not initialized:
        load_or_train()
        initialized = True

    knob_value = int(Bridge.call("read_knob"))
    pressed = int(Bridge.call("read_pressed"))
    now = time.monotonic()
    sample = (now, knob_value)

    if pressed == 1 and last_pressed == 0:
        pressed_at = now
        reset_capture()
        if mode == "capturing":
            mode = "training_ready"
            print("Recording cancelled. Release the knob to start again.")

    if mode == "live" and pressed == 1 and pressed_at is not None:
        if now - pressed_at >= HOLD_TO_RETRAIN_SECONDS:
            ignore_next_release = True
            begin_training(clear_saved_model=True)
            pressed_at = None

    if pressed == 0 and last_pressed == 1:
        if ignore_next_release:
            ignore_next_release = False
        elif mode == "training_ready":
            mode = "capturing"
            capture_armed_at = now
            Bridge.call("show_mode", 2, 8)
            print("Recording now...")
        # Button movement should not become part of the next example.
        last_sample = sample
        pressed_at = None

    if pressed == 0 and last_sample is not None and mode in ("capturing", "live"):
        update_capture(sample)

    last_sample = sample
    last_pressed = pressed
    time.sleep(SAMPLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    print("UNO Q Anomaly Dial starting...")
    App.run(user_loop=loop)
