"""
Automatic checks for risk.py. Run them with:  python -m pytest
If everything is fine you see "passed". This proves the logic works.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collector import handle_message  # noqa: E402
from risk import assess_ship, distance_nm, is_bound_for_hamburg, parse_ais_eta, sea_area  # noqa: E402

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def eta_in(hours):
    t = NOW + timedelta(hours=hours)
    return {"Month": t.month, "Day": t.day, "Hour": t.hour, "Minute": t.minute}


def ship(**extra):
    base = {"mmsi": "1", "name": "TEST", "lat": 50.35, "lon": -1.2, "sog": 16.0, "nav_status": 0,
            "last_position_utc": NOW.isoformat(), "destination": "DEHAM"}
    base.update(extra)
    return base


def test_destination_matching():
    assert is_bound_for_hamburg("DEHAM")
    assert is_bound_for_hamburg("DE HAM")
    assert is_bound_for_hamburg("hamburg, germany")
    assert is_bound_for_hamburg("NLRTM>DEHAM")
    assert not is_bound_for_hamburg("DEHAM>NLRTM")    # leaving Hamburg, not going there
    assert not is_bound_for_hamburg("ROTTERDAM")
    assert not is_bound_for_hamburg("")


def test_distance_rotterdam_hamburg_is_realistic():
    # Straight line Rotterdam - Hamburg is about 220 nm
    assert 200 < distance_nm((51.95, 4.14), (53.54, 9.97)) < 240


def test_sea_areas():
    assert sea_area(36.4, -3.1) == "Mediterranean"
    assert sea_area(50.3, -1.2) == "English Channel"
    assert sea_area(54.2, 7.5) == "North Sea"
    assert sea_area(53.55, 9.8) == "Elbe river"


def test_eta_without_year_is_placed_in_next_year_when_needed():
    december_now = datetime(2026, 12, 30, tzinfo=timezone.utc)
    eta = parse_ais_eta({"Month": 1, "Day": 3, "Hour": 8, "Minute": 0}, december_now)
    assert eta.year == 2027
    assert parse_ais_eta({"Month": 0, "Day": 0, "Hour": 24, "Minute": 60}, NOW) is None


def test_flags():
    assert assess_ship(ship(eta=eta_in(33)), NOW)["Flag"] == "🟢"
    assert assess_ship(ship(eta=eta_in(10)), NOW)["Flag"] == "🔴"                    # far too optimistic
    assert assess_ship(ship(eta=None), NOW)["Status"] == "No ETA sent"
    assert assess_ship(ship(sog=0.1, nav_status=1, eta=eta_in(30)), NOW)["Status"] == "Stopped"
    old = (NOW - timedelta(hours=30)).isoformat()
    assert assess_ship(ship(last_position_utc=old, eta=eta_in(30)), NOW)["Status"] == "Data too old"
    assert assess_ship(ship(lat=53.55, lon=9.85, eta=eta_in(1)), NOW)["Flag"] == "⚪"


def test_collector_reads_aisstream_messages():
    ships = {}
    handle_message(ships, {
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 211000000, "ShipName": "TEST SHIP  ", "latitude": 36.4, "longitude": -3.1},
        "Message": {"PositionReport": {"UserID": 211000000, "Latitude": 36.4, "Longitude": -3.1,
                                       "Sog": 17.5, "Cog": 270.0, "NavigationalStatus": 0}},
    })
    handle_message(ships, {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 211000000, "ShipName": "TEST SHIP"},
        "Message": {"ShipStaticData": {"Destination": "DEHAM", "Type": 71, "Name": "TEST SHIP",
                                       "Eta": {"Month": 11, "Day": 2, "Hour": 6, "Minute": 0}}},
    })
    s = ships["211000000"]
    assert s["name"] == "TEST SHIP"
    assert s["sog"] == 17.5 and s["destination"] == "DEHAM"
    assert s["seen_in_mediterranean"] is True
