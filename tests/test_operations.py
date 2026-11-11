"""
Checks for operations.py: ship size, the timeline after the berth, and the cost of delay.
Expected values come from worked examples, not from re-running the code's own formulas.
Run with:  python -m pytest
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta, timezone  # noqa: E402

from operations import after_berth, delay_cost, estimate_teu, money  # noqa: E402

BERTH = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)


def test_ship_size_comes_from_length():
    assert estimate_teu(366, None) == (14000, "length 366 m")       # a 366 m ship is a ~14,000 TEU class ship
    assert estimate_teu(200, 12.0) == (2500, "length 200 m")        # length wins over draught


def test_draught_alone_is_not_enough_to_guess_size():
    # A part-loaded ship floats high: MAERSK SEOUL reported 9.6 m and came out at a far-too-small 1,700 TEU.
    assert estimate_teu(None, 9.6) == (None, "size unknown")
    assert estimate_teu(None, None) == (None, "size unknown")


def hours_after_berth(moment):
    return (moment - BERTH).total_seconds() / 3600


def test_unloading_a_large_ship_worked_example():
    # 14,000 TEU: 5 cranes. 10-25 % unloaded in Hamburg = 848-2,121 moves (1.65 TEU per move).
    # Fastest: 848 moves at the per-ship ceiling of ~146 moves/h = 5.8 h. Slowest: 2,121 moves at 5 x 25 = 125/h = 17.0 h.
    plan = after_berth(BERTH, 14000, warehouse_km=30)
    assert plan["cranes"] == 5
    fast, slow = plan["unloading_hours"]
    assert abs(fast - 5.8) < 0.1 and abs(slow - 17.0) < 0.1
    first_earliest, first_latest = plan["first_ready"]
    assert hours_after_berth(first_earliest) == 2.5        # 0.5 h to start + 2 h to release
    assert hours_after_berth(first_latest) == 7.5          # 1.5 h to start + 6 h to release


def test_timeline_steps_happen_in_order():
    plan = after_berth(BERTH, 4500, warehouse_km=30)
    steps = ["unloading_starts", "first_ready", "all_ready", "at_warehouse_all"]
    for step in steps:
        earliest, latest = plan[step]
        assert earliest <= latest, step
    for before, after in zip(steps, steps[1:]):
        assert plan[before][0] <= plan[after][0], (before, after)


def test_a_further_warehouse_is_reached_later():
    near = after_berth(BERTH, 4500, warehouse_km=10)["at_warehouse_first"][0]
    far = after_berth(BERTH, 4500, warehouse_km=120)["at_warehouse_first"][0]
    assert far - near == timedelta(hours=110 / 50)          # 110 km more at the fastest truck speed (50 km/h)


def test_cost_of_one_day_late_worked_example():
    # 2,500 TEU ship, 24 h late. Ship time: one day at the New ConTex band for 2,000-3,000 TEU ($36,000-41,000).
    # Cargo: 250-625 TEU unloaded in Hamburg x $40,000 x 5-10 % a year / 365 = $1,370-6,849 for one day.
    cost = delay_cost(2500, 24)
    assert cost["ship"] == (36000, 41000)
    assert round(cost["cargo"][0]) == 1370 and round(cost["cargo"][1]) == 6849
    assert money(*cost["total"]) == "$37k–$48k"


def test_no_cost_when_the_ship_is_not_late():
    assert delay_cost(2500, 0) is None
    assert delay_cost(2500, -5) is None
    assert delay_cost(2500, None) is None
