"""
Checks for history.py: rebuilding real arrivals from snapshots, judging them, and the shipping-line scorecard.
No git needed: we build small made-up snapshots with known answers.
Run with:  python -m pytest
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from history import UNKNOWN_LINE, build_arrivals, judge, load_arrivals, scorecard  # noqa: E402

T0 = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
AT_SEA = (54.0, 7.5)            # North Sea, under way
IN_HAMBURG = (53.54, 9.97)      # moored at the port


def eta(hours):
    t = T0 + timedelta(hours=hours)
    return {"Month": t.month, "Day": t.day, "Hour": t.hour, "Minute": t.minute}


def sighting(mmsi, name, where, hours, promised_in_h, moored=False, ship_type=71):
    lat, lon = where
    return {"mmsi": mmsi, "name": name, "destination": "DEHAM", "ship_type": ship_type, "lat": lat, "lon": lon,
            "sog": 0.0 if moored else 12.0, "nav_status": 5 if moored else 0,
            "last_position_utc": (T0 + timedelta(hours=hours)).isoformat(),
            "eta": eta(promised_in_h) if promised_in_h is not None else None}


def snapshots(*sightings_per_snapshot):
    return [{"ships": {s["mmsi"]: s for s in group}} for group in sightings_per_snapshot]


def test_berthing_within_a_day_of_the_promise_is_on_time():
    history = snapshots([sighting("211000001", "MSC TESTA", AT_SEA, 0, promised_in_h=20)],
                        [sighting("211000001", "MSC TESTA", IN_HAMBURG, 21, 20, moored=True)])
    [arrival] = build_arrivals(history)
    assert arrival["line"] == "MSC"
    assert arrival["arrived_after"] == T0.isoformat()                         # last seen under way
    assert arrival["arrived_by"] == (T0 + timedelta(hours=21)).isoformat()    # first seen moored
    assert judge(arrival) == "On time"


def test_still_at_sea_a_day_after_the_promise_is_late():
    history = snapshots([sighting("211000002", "LATE SHIP", AT_SEA, 0, promised_in_h=5)],
                        [sighting("211000002", "LATE SHIP", AT_SEA, 33, 5)],      # 28 h past its promise
                        [sighting("211000002", "LATE SHIP", IN_HAMBURG, 36, 5, moored=True)])
    assert judge(build_arrivals(history)[0]) == "Late"


def test_a_window_across_the_limit_is_unclear_not_guessed():
    # Promised in 5 h; last seen under way at 10 h, first seen moored at 40 h: it berthed between 5 h and 35 h
    # after its promise, so it may or may not have been more than a day late.
    history = snapshots([sighting("211000003", "MAYBE SHIP", AT_SEA, 10, promised_in_h=5)],
                        [sighting("211000003", "MAYBE SHIP", IN_HAMBURG, 40, 5, moored=True)])
    assert judge(build_arrivals(history)[0]) == "Unclear"


def test_a_ship_first_seen_in_port_made_no_promise_we_saw():
    history = snapshots([sighting("211000004", "ALREADY HERE", IN_HAMBURG, 0, 0, moored=True)])
    assert build_arrivals(history) == []


def test_a_shipping_line_needs_three_judged_arrivals_for_a_score():
    on_time = {"line": "MSC", "promised_eta": T0.isoformat(), "arrived_after": T0.isoformat(),
               "arrived_by": (T0 + timedelta(hours=3)).isoformat()}
    late = {**on_time, "arrived_after": (T0 + timedelta(hours=30)).isoformat(),
            "arrived_by": (T0 + timedelta(hours=33)).isoformat()}
    rows = {r["Shipping line"]: r for r in scorecard([on_time, on_time, late, {**on_time, "line": "ZIM"}])}
    assert rows["MSC"]["On time"] == 2 and rows["MSC"]["Late"] == 1
    assert abs(rows["MSC"]["Schedule reliability"] - 2 / 3) < 1e-9
    assert rows["ZIM"]["Schedule reliability"] is None                   # one arrival: too few to score
    assert rows["All ships"]["Arrivals"] == 4


def test_a_broken_or_hostile_arrivals_file_never_reaches_the_page(tmp_path):
    path = tmp_path / "arrivals.json"
    good = {"mmsi": "211000005", "ship": "<b>[CLICK](HTTP://X.CO)</b> AND A VERY LONG NAME INDEED", "line": "MSC",
            "first_seen": T0.isoformat(), "promised_eta": T0.isoformat(),
            "arrived_after": T0.isoformat(), "arrived_by": (T0 + timedelta(hours=3)).isoformat()}
    backwards = {**good, "arrived_after": (T0 + timedelta(hours=9)).isoformat()}     # window ends before it starts
    path.write_text(json.dumps({"updated_utc": "not a date",
                                "arrivals": [good, backwards, "not a record", {"arrived_by": 5}]}))
    arrivals, updated = load_arrivals(path)
    assert len(arrivals) == 1 and updated is None
    assert len(arrivals[0]["ship"]) <= 20                       # cut to the AIS name length, like every name
    path.write_text("not json")
    assert load_arrivals(path) == ([], None)
    assert load_arrivals(tmp_path / "missing.json") == ([], None)



def test_only_cargo_ships_count_towards_reliability():
    # Review finding: "Line unknown" mixed in harbour craft. A tug (AIS type 52) is not a cargo ship.
    history = snapshots([sighting("211000006", "HARBOUR TUG", AT_SEA, 0, 20, ship_type=52)],
                        [sighting("211000006", "HARBOUR TUG", IN_HAMBURG, 21, 20, moored=True, ship_type=52)])
    assert build_arrivals(history) == []


def test_berthing_more_than_a_day_before_the_promise_is_early():
    history = snapshots([sighting("211000007", "QUICK SHIP", AT_SEA, 0, promised_in_h=40)],
                        [sighting("211000007", "QUICK SHIP", IN_HAMBURG, 10, 40, moored=True)])
    assert judge(build_arrivals(history)[0]) == "Early"           # berthed 30-40 h before its promise


def test_no_reported_eta_means_no_judgement():
    history = snapshots([sighting("211000008", "SILENT SHIP", AT_SEA, 0, promised_in_h=None)],
                        [sighting("211000008", "SILENT SHIP", IN_HAMBURG, 21, None, moored=True)])
    assert judge(build_arrivals(history)[0]) == "No ETA"


def test_average_delay_uses_the_middle_of_the_berthing_window():
    # Promised at 20 h; berthed between 0 h and 21 h -> middle 10.5 h -> 9.5 h early. Checked through the scorecard.
    arrival = {"line": "MSC", "promised_eta": (T0 + timedelta(hours=20)).isoformat(),
               "arrived_after": T0.isoformat(), "arrived_by": (T0 + timedelta(hours=21)).isoformat()}
    assert scorecard([arrival])[0]["Average delay (h)"] == -9.5


def test_scorecard_order_and_judged_count():
    base = {"promised_eta": T0.isoformat(), "arrived_after": T0.isoformat(),
            "arrived_by": (T0 + timedelta(hours=3)).isoformat()}
    no_eta = {**base, "promised_eta": None}
    rows = scorecard([{**base, "line": UNKNOWN_LINE}, {**base, "line": "MSC"}, {**no_eta, "line": "MSC"}])
    assert [r["Shipping line"] for r in rows] == ["All ships", "MSC", UNKNOWN_LINE]
    msc = rows[1]
    assert msc["Arrivals"] == 2 and msc["Judged"] == 1             # the one without an ETA isn't judged


def test_a_ship_with_no_reported_type_does_not_count():
    # Review finding: the score rested mostly on unidentified ships. No reported type = maybe not a cargo ship.
    history = snapshots([sighting("211000010", "MYSTERY", AT_SEA, 0, 20, ship_type=None)],
                        [sighting("211000010", "MYSTERY", IN_HAMBURG, 21, 20, moored=True, ship_type=None)])
    assert build_arrivals(history) == []
