"""
Checks for eta_model.py (the experimental ML estimate). No git or internet needed:
we build small made-up snapshots and check the learning steps.
Run with:  python -m pytest
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eta_model import build_examples, fit, leave_one_ship_out, load_model, predict_hours, train  # noqa: E402

T0 = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)


def snapshot(ships):
    return {"meta": {}, "ships": {s["mmsi"]: s for s in ships}}


def ship(mmsi, lat, lon, when, sog=12.0):
    return {"mmsi": mmsi, "name": f"TEST {mmsi}", "destination": "DEHAM", "ship_type": 71,
            "lat": lat, "lon": lon, "sog": sog, "nav_status": 0, "last_position_utc": when.isoformat()}


def test_example_is_built_from_at_sea_then_arriving():
    at_sea = snapshot([ship("211000001", 54.0, 7.5, T0)])                      # North Sea
    arrived = snapshot([ship("211000001", 53.54, 9.97, T0 + timedelta(hours=10), sog=0)])   # in Hamburg
    examples = build_examples([at_sea, arrived])
    assert len(examples) == 1
    assert examples[0]["actual_hours"] == 10.0
    assert examples[0]["calc_hours"] > 0


def test_ship_never_seen_arriving_gives_no_example():
    assert build_examples([snapshot([ship("211000002", 54.0, 7.5, T0)])]) == []


def test_fit_learns_a_simple_rule():
    # Made-up rule: real hours = 1.5 × calculated + 2, plus 6 more if stopped.
    examples = [{"mmsi": str(i), "calc_hours": h, "stopped": s, "actual_hours": 1.5 * h + 2 + (6 if s else 0)}
                for i, (h, s) in enumerate([(5, False), (10, False), (20, True), (30, False), (8, True)])]
    a, b, c = fit(examples)
    assert abs(a - 1.5) < 0.01 and abs(b - 6) < 0.01 and abs(c - 2) < 0.01
    assert abs(predict_hours([a, b, c], 10, False) - 17) < 0.01


def test_prediction_is_never_negative():
    assert predict_hours([1.0, 0.0, -100.0], 5, False) == 0.0


def test_leave_one_ship_out_reports_both_errors():
    examples = [{"mmsi": str(i), "calc_hours": h, "stopped": False, "actual_hours": h + 4}
                for i, h in enumerate([5, 10, 15, 20])]
    result = leave_one_ship_out(examples)
    assert result["calculated_mae_h"] == 4.0          # the plain calculation is always 4 h short
    assert result["model_mae_h"] < 1.0                # the model learns the +4 h


def test_too_few_ships_means_no_model():
    at_sea = snapshot([ship("211000003", 54.0, 7.5, T0)])
    arrived = snapshot([ship("211000003", 53.54, 9.97, T0 + timedelta(hours=10), sog=0)])
    assert train([at_sea, arrived])["coefficients"] is None


def test_broken_model_file_is_ignored(tmp_path):
    bad = tmp_path / "eta_model.json"
    bad.write_text(json.dumps({"coefficients": ["DROP TABLE", 1, 2]}))
    assert load_model(bad) is None
    bad.write_text("not json")
    assert load_model(bad) is None
    assert load_model(tmp_path / "missing.json") is None
