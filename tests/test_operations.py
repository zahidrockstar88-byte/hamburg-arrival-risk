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
    assert estimate_teu(366) == (14000, "length 366 m")       # a 366 m ship is a ~14,000 TEU class ship
    assert estimate_teu(200) == (2500, "length 200 m")


def test_without_a_length_the_size_is_unknown():
    # Draught is no longer used: a part-loaded ship floats high, so MAERSK SEOUL (9.6 m) looked like 1,700 TEU.
    assert estimate_teu(None) == (None, "size unknown")
    assert estimate_teu(30) == (None, "size unknown")          # far too short to be a container ship


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
    # 2,500 TEU ship, 24 h late. Ship time: New ConTex 2,500 TEU class, $37,227-38,665 a day (midpoint $37,946),
    # shown as +-5 %: $36,049-39,843. Cargo: 250-625 TEU x $40,000 x 5-10 % a year / 365 = $1,370-6,849.
    cost = delay_cost(2500, 24)
    assert round(cost["ship"][0]) == 36049 and round(cost["ship"][1]) == 39843
    assert round(cost["cargo"][0]) == 1370 and round(cost["cargo"][1]) == 6849
    assert cost["rate_basis"] == "New ConTex charter index"


def test_ship_cost_has_no_jump_between_size_bands():
    # Review finding: 3,000 TEU cost $36-41k a day but 3,001 TEU cost $50-60k.
    just_below, just_above = delay_cost(3000, 24)["ship"], delay_cost(3001, 24)["ship"]
    assert abs(just_above[0] - just_below[0]) < 100


def test_ships_bigger_than_the_sourced_index_are_labelled_as_estimates():
    assert delay_cost(4250, 24)["rate_basis"] == "New ConTex charter index"
    assert delay_cost(10000, 24)["rate_basis"] == "estimate (bigger than the sourced index classes)"


def test_no_cost_when_the_ship_is_not_late():
    assert delay_cost(2500, 0) is None
    assert delay_cost(2500, -5) is None
    assert delay_cost(2500, None) is None


def test_a_bigger_ship_never_unloads_faster():
    # Review finding: at the crane-count steps, 3,001 TEU unloaded faster (1.3-4.5 h) than 3,000 TEU (1.7-6.1 h).
    previous = (0, 0)
    for teu in range(1000, 20001, 250):
        plan = after_berth(BERTH, teu, warehouse_km=30)
        fast, slow = plan["unloading_hours"]
        assert fast >= previous[0] - 1e-9 and slow >= previous[1] - 1e-9, teu
        previous = (fast, slow)


def test_containers_can_also_leave_by_train():
    # Spec: "ready for trucks or rail". Trains leave Hamburg's terminals several times a day:
    # a box waits 2-12 h for its train after it is ready (assumption).
    plan = after_berth(BERTH, 14000, warehouse_km=30)
    first_ready, all_ready = plan["first_ready"], plan["all_ready"]
    earliest_train, latest_train = plan["on_a_train"]
    assert hours_after_berth(earliest_train) == hours_after_berth(first_ready[0]) + 2
    assert hours_after_berth(latest_train) == hours_after_berth(all_ready[1]) + 12
