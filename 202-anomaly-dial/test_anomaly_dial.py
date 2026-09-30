"""Run with: python3 -B 202-anomaly-dial/test_anomaly_dial.py"""

import contextlib
import io
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent / "workshop-app" / "python"))
from anomaly_model import extract_features, load, predict, save, train


def check():
    normal = [(index * 0.05, index) for index in range(21)]
    features = extract_features(normal)
    baseline = train([extract_features(normal[:length]) for length in (19, 20, 21, 20, 21)])
    assert not predict(baseline, features)["anomalous"]
    assert extract_features([(-1, 0)] + normal + [(2, 20)]) == features
    assert extract_features([(t, 500 - value) for t, value in normal]) == features
    irregular = extract_features([(0, 0), (0.4, 4), (0.5, 6), (1.2, 12)])
    assert all(math.isclose(a, b) for a, b in zip(irregular, [1.2, 10, 20, 0]))
    for unusual in (
        [(t, value * 4) for t, value in normal],  # Faster.
        [(t, value % 2) for t, value in normal],  # Reversals.
        [(index * 0.05, index) for index in range(71)],  # Longer.
    ):
        assert predict(baseline, extract_features(unusual))["anomalous"]
    identical = train([features] * 5)
    assert all(scale > 0 for scale in identical["scales"])
    assert predict(identical, features)["score"] == 0
    boundary_model = {"means": [1, 20, 20, 0], "scales": [1, 5, 10, 1]}
    assert not predict(boundary_model, [4, 20, 20, 0])["anomalous"]
    assert predict(boundary_model, [4.01, 20, 20, 0])["anomalous"]
    for bad in ([], [(0, 0), (1, 0)], [(0, 0), (0, 10)], [(0, 0), (1, math.nan)]):
        try:
            extract_features(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted invalid samples: {bad}")

    with TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
        path = Path(directory) / "data" / "anomaly_model.json"
        assert load(path) is None
        save(baseline, path)
        assert load(path) == baseline
        assert not path.with_suffix(".tmp").exists()
        for bad in ([], {}, {**baseline, "scales": [1, 1, 1, 0]},
                    {**baseline, "means": [math.nan, 20, 20, 0]}):
            path.write_text(json.dumps(bad))
            try:
                load(path)
            except ValueError:
                pass
            else:
                raise AssertionError(f"Accepted invalid saved model: {bad}")

        inputs = {"read_knob": 0, "read_pressed": 0}
        calls = []

        def bridge_call(name, *args):
            if name in inputs:
                return inputs[name]
            calls.append((name, *args))

        utilities = ModuleType("arduino.app_utils")
        utilities.Bridge = SimpleNamespace(call=bridge_call)
        utilities.App = SimpleNamespace()
        sys.modules["arduino"] = ModuleType("arduino")
        sys.modules["arduino.app_utils"] = utilities
        import main as app

        now = 0.0
        app.MODEL_PATH = path
        app.time = SimpleNamespace(monotonic=lambda: now, sleep=lambda _: None)

        def tick(position=None, pressed=0, seconds=0.05):
            nonlocal now
            if position is not None:
                inputs["read_knob"] = position
            inputs["read_pressed"] = pressed
            now += seconds
            app.loop()

        def move(step=1, count=20):
            for _ in range(count):
                tick(inputs["read_knob"] + step)
            for _ in range(7):
                tick()

        tick()  # Corrupt saved model falls back to training.
        assert app.mode == "training_ready"
        tick(pressed=1)
        tick()
        tick(seconds=5.1)  # No movement: retry without accepting an example.
        assert app.mode == "training_ready" and not app.training_examples
        assert ("show_mode", 4, 3) in calls

        tick(pressed=1)
        tick()
        move(count=2)  # Too little movement: retry.
        assert app.mode == "training_ready" and not app.training_examples
        tick(pressed=1)
        tick()
        tick(inputs["read_knob"] + 10)
        tick(pressed=1)  # Cancel an in-progress example.
        tick()
        assert app.mode == "capturing" and not app.capture_samples
        move()
        assert len(app.training_examples) == 1

        for _ in range(app.TRAINING_EXAMPLES - 1):
            tick(pressed=1)
            tick()
            move()
        assert app.mode == "live" and load(path) == app.model
        app.initialized = False
        tick()  # Restart loads the baseline and skips training.
        assert app.mode == "live"
        calls.clear()
        move()
        assert any(call[:2] == ("show_result", 0) for call in calls)
        calls.clear()
        move(step=4)
        assert any(call[:2] == ("show_result", 1) for call in calls)
        calls.clear()
        for _ in range(12):
            tick(inputs["read_knob"] + 1)
            tick(inputs["read_knob"] - 1)
        for _ in range(7):
            tick()
        assert any(call[:2] == ("show_result", 1) for call in calls)
        calls.clear()
        for _ in range(90):
            tick(inputs["read_knob"] + 1)
        assert any(call[:2] == ("show_result", 1) for call in calls)  # Four-second cap.

        tick(pressed=1)
        tick(pressed=1, seconds=3.1)
        assert app.mode == "training_ready" and not path.exists()
        tick()
        assert app.mode == "training_ready" and not app.training_examples

        def cannot_save(*args):
            raise OSError("Simulated full disk")

        app.save = cannot_save
        app.training_examples = [features] * (app.TRAINING_EXAMPLES - 1)
        tick(pressed=1)
        tick()
        move()
        assert app.mode == "live" and app.model is not None and not path.exists()

    print("PASS: anomaly features, scoring, persistence, and simulated recording/live/retrain flow")


if __name__ == "__main__":
    check()
