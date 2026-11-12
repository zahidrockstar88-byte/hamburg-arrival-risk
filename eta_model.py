"""
eta_model.py - An EXPERIMENTAL machine-learning correction for the calculated ETA.

The idea in plain words:
  Our calculated ETA is "distance ÷ speed". Real ships are usually a bit slower
  or faster than that (waiting for a pilot, the tide, a berth). If we look at
  ships that really arrived, we can LEARN how wrong the calculation usually is,
  and correct it.

Where the examples come from:
  The GitHub Action saves data/ships.json every ~3 hours, and git keeps every
  saved version. So the git history is a list of snapshots. For each ship we
  look for: "seen out at sea in one snapshot" -> "seen moored in Hamburg in a later one".
  That gives one example: what we calculated then, and how long it really took.

The model:
  A simple linear regression (a straight-line fit), so it is easy to explain:
      real hours = a × calculated hours + b × (stopped? 1 : 0) + c
  It learns a, b and c from the examples.

How we check it honestly:
  "Leave one ship out": train on all ships except one, predict that one ship,
  repeat for every ship, and average the errors. We compare that error with
  the plain calculated ETA. If the model is not better, the dashboard says so.

Run it (it reads the git history, so run it inside the project folder):
    python eta_model.py
It writes model/eta_model.json, which app.py reads.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import config
from risk import ARRIVAL_FLAGS, NO_ETA_TO_JUDGE, parse_time
from history import collect_sightings, load_snapshots_from_git   # shared with history.py

MODEL_FILE = config.PROJECT_DIR / "model" / "eta_model.json"
MIN_SHIPS_TO_TRAIN = 10        # below this, we don't train at all
MAX_HOURS = 24 * 14            # ignore examples longer than two weeks (probably broken data)


# ---------------------------------------------------------------------------
# 2. Examples: "what we calculated" -> "how long it really took"
# ---------------------------------------------------------------------------
def build_examples(snapshots: list[dict]) -> list[dict]:
    """
    Turn snapshots into training examples. The arrival time is the first time we
    see the ship moored in Hamburg (🔵 Arrived, see GLOSSARY.md: arrival = berthing),
    so it is only accurate to about the gap between snapshots (~3 hours).
    """
    sightings = {}                         # mmsi -> {time seen: dashboard row at that moment}
    for mmsi, by_time in collect_sightings(snapshots).items():
        sightings[mmsi] = {}
        for seen, (row, _ship) in by_time.items():
            sightings[mmsi][seen] = row

    examples = []
    for mmsi, by_time in sightings.items():
        times = sorted(by_time)
        arrived_at = next((t for t in times if by_time[t]["Flag"] == "🔵"), None)
        if arrived_at is None:
            continue
        for t in times:
            row = by_time[t]
            if t >= arrived_at or row["Flag"] in ARRIVAL_FLAGS:
                continue                       # only learn from sightings before the final approach
            actual = (arrived_at - t).total_seconds() / 3600
            if 0 < actual <= MAX_HOURS:
                examples.append({"mmsi": mmsi, "calc_hours": row["calc_hours"],
                                 "stopped": row["stopped"], "actual_hours": round(actual, 2)})
    return examples


# ---------------------------------------------------------------------------
# 3. The model: a straight-line fit
# ---------------------------------------------------------------------------
def _features(calc_hours: float, stopped: bool) -> list[float]:
    return [calc_hours, 1.0 if stopped else 0.0, 1.0]       # the last 1.0 is the constant "c"


def fit(examples: list[dict]) -> list[float]:
    """Learn a, b, c with least squares (the line that is closest to all examples)."""
    x = np.array([_features(e["calc_hours"], e["stopped"]) for e in examples])
    y = np.array([e["actual_hours"] for e in examples])
    coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    return [float(c) for c in coefficients]


def predict_hours(coefficients: list[float], calc_hours: float, stopped: bool) -> float:
    """Predicted real hours to go. Never less than zero."""
    return max(0.0, float(np.dot(coefficients, _features(calc_hours, stopped))))


def leave_one_ship_out(examples: list[dict]) -> dict:
    """Honest test: predict each ship with a model that never saw that ship."""
    ships = sorted({e["mmsi"] for e in examples})
    model_errors, plain_errors = [], []
    for mmsi in ships:
        train = [e for e in examples if e["mmsi"] != mmsi]
        test = [e for e in examples if e["mmsi"] == mmsi]
        if len({e["mmsi"] for e in train}) < 2:
            continue
        coefficients = fit(train)
        for e in test:
            model_errors.append(abs(predict_hours(coefficients, e["calc_hours"], e["stopped"]) - e["actual_hours"]))
            plain_errors.append(abs(e["calc_hours"] - e["actual_hours"]))
    if not model_errors:
        return {"model_mae_h": None, "calculated_mae_h": None}
    return {"model_mae_h": round(float(np.mean(model_errors)), 1),
            "calculated_mae_h": round(float(np.mean(plain_errors)), 1)}


def train(snapshots: list[dict]) -> dict:
    """Build examples, test honestly, then fit on everything. Returns what gets saved."""
    examples = build_examples(snapshots)
    n_ships = len({e["mmsi"] for e in examples})
    result = {
        "trained_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshots": len(snapshots),
        "examples": len(examples),
        "ships": n_ships,
        "coefficients": None,
        **leave_one_ship_out(examples),
    }
    if n_ships >= MIN_SHIPS_TO_TRAIN:
        result["coefficients"] = fit(examples)
    return result


# ---------------------------------------------------------------------------
# 4. Saving and loading
# ---------------------------------------------------------------------------
def _number_or_none(value):
    """A real number (not True/False), or None."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def load_model(path: Path = MODEL_FILE) -> dict | None:
    """
    Read the saved model, or None if it is missing, broken, or was not trained.
    The file is written by a bot from radio data, so every value is checked before the page shows it.
    """
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict):
        return None
    coefficients = saved.get("coefficients")
    if not (isinstance(coefficients, list) and len(coefficients) == 3
            and all(_number_or_none(c) is not None for c in coefficients)):
        return None
    trained = parse_time(saved.get("trained_utc")) if isinstance(saved.get("trained_utc"), str) else None
    return {
        "coefficients": [float(c) for c in coefficients],
        "ships": int(_number_or_none(saved.get("ships")) or 0),
        "examples": int(_number_or_none(saved.get("examples")) or 0),
        "snapshots": int(_number_or_none(saved.get("snapshots")) or 0),
        "model_mae_h": _number_or_none(saved.get("model_mae_h")),
        "calculated_mae_h": _number_or_none(saved.get("calculated_mae_h")),
        "trained_utc": trained,
    }


def ml_eta_for(row: dict, model: dict | None) -> datetime | None:
    """
    The experimental ML ETA for one dashboard row, or None when there is no model or nothing to estimate
    (the ship is arriving, has arrived, or is still in another port with an unknown departure time).
    """
    if not model or row["Flag"] in NO_ETA_TO_JUDGE:
        return None
    predicted = predict_hours(model["coefficients"], row["calc_hours"], row["stopped"])
    return row["calc_eta_utc"] + timedelta(hours=predicted - row["calc_hours"])


def main() -> None:
    model = train(load_snapshots_from_git())
    MODEL_FILE.parent.mkdir(exist_ok=True)
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=1)
    print(f"Snapshots: {model['snapshots']}, examples: {model['examples']}, ships: {model['ships']}")
    if model["coefficients"] is None:
        print(f"Not trained: need at least {MIN_SHIPS_TO_TRAIN} ships that were seen at sea and then arriving.")
    else:
        a, b, c = model["coefficients"]
        print(f"Model: real hours = {a:.2f} × calculated hours + {b:.1f} if not moving + {c:.1f}")
    print(f"Average error (leave one ship out): model {model['model_mae_h']} h, "
          f"calculated ETA {model['calculated_mae_h']} h")


if __name__ == "__main__":
    main()
