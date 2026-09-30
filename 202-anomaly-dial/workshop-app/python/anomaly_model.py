"""Dependency-free motion features and a baseline-only anomaly detector."""

import json
import math
from pathlib import Path
from statistics import mean, pstdev


MODEL_VERSION = 1
FEATURE_NAMES = ("duration_s", "mean_speed", "peak_speed", "reversals")
MINIMUM_TRAVEL = 6
MINIMUM_SCALES = (0.20, 5.0, 10.0, 1.0)
ANOMALY_THRESHOLD = 3.0


def extract_features(samples):
    """Convert (monotonic seconds, knob position) samples into motion features."""
    if len(samples) < 2:
        raise ValueError("Not enough movement; turn at least six knob steps")
    if any(len(sample) != 2 for sample in samples):
        raise ValueError("Each sample needs a timestamp and a knob position")
    if any(not math.isfinite(value) for sample in samples for value in sample):
        raise ValueError("Samples must contain finite numbers")

    intervals = [right[0] - left[0] for left, right in zip(samples, samples[1:])]
    if any(interval <= 0 for interval in intervals):
        raise ValueError("Sample timestamps must increase")
    deltas = [right[1] - left[1] for left, right in zip(samples, samples[1:])]
    active = [index for index, delta in enumerate(deltas) if delta != 0]
    travel = sum(abs(delta) for delta in deltas)
    if travel < MINIMUM_TRAVEL:
        raise ValueError("Not enough movement; turn at least six knob steps")

    duration = samples[active[-1] + 1][0] - samples[active[0]][0]
    peak_speed = max(abs(delta) / interval for delta, interval in zip(deltas, intervals))
    signs = [1 if deltas[index] > 0 else -1 for index in active]
    reversals = sum(left != right for left, right in zip(signs, signs[1:]))
    return [duration, travel / duration, peak_speed, float(reversals)]


def _validate_vector(values):
    if not isinstance(values, (list, tuple)) or len(values) != len(FEATURE_NAMES):
        raise ValueError("Expected four motion features")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError("Features must contain finite numbers")
    if any(value < 0 for value in values) or any(value <= 0 for value in values[:3]):
        raise ValueError("Duration and speeds must be positive; reversals cannot be negative")


def train(examples):
    """Learn the mean and spread of normal movement, without anomaly examples."""
    if len(examples) < 5:
        raise ValueError("Record at least five normal examples")
    for row in examples:
        _validate_vector(row)
    columns = list(zip(*examples))
    return {
        "version": MODEL_VERSION,
        "means": [mean(column) for column in columns],
        "scales": [max(pstdev(column), floor) for column, floor in zip(columns, MINIMUM_SCALES)],
    }


def predict(model, features):
    """Return the largest standardized deviation, not a probability."""
    _validate_vector(features)
    deviations = {
        name: abs(value - center) / scale
        for name, value, center, scale in zip(
            FEATURE_NAMES, features, model["means"], model["scales"]
        )
    }
    strongest = max(deviations, key=deviations.get)
    score = deviations[strongest]
    # ponytail: independent features miss unusual combinations; use covariance if needed.
    return {"score": score, "anomalous": score > ANOMALY_THRESHOLD, "feature": strongest}


def save(model, path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(model, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(destination)


def load(path):
    source = Path(path)
    if not source.exists():
        return None
    model = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(model, dict) or model.get("version") != MODEL_VERSION:
        raise ValueError("Saved anomaly model uses an unsupported format or version")
    _validate_vector(model.get("means"))
    _validate_vector(model.get("scales"))
    if any(scale <= 0 for scale in model["scales"]):
        raise ValueError("Saved anomaly model scales must be positive")
    return model
