"""
Automatic checks for risk.py. Run them with:  python -m pytest
If everything is fine you see "passed". This proves the logic works.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collector import handle_message  # noqa: E402
from risk import (CONTAINER_LIKELY, CONTAINER_UNKNOWN, CONTAINER_UNLIKELY,  # noqa: E402
                  assess_ship, container_guess, container_terminal, distance_nm, is_bound_for_hamburg,
                  is_cargo_type, is_moored, parse_ais_eta, sea_area, shipping_line)

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
    assert assess_ship(ship(sog=0.1, nav_status=1, eta=eta_in(30)), NOW)["Status"] == "Waiting"
    old = (NOW - timedelta(hours=30)).isoformat()
    assert assess_ship(ship(last_position_utc=old, eta=eta_in(30)), NOW)["Status"] == "Data too old"
    assert assess_ship(ship(lat=53.55, lon=9.85, eta=eta_in(1)), NOW)["Flag"] == "⚪"    # still moving: Arriving


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


# ---------------------------------------------------------------------------
# Container ships and shipping lines
# ---------------------------------------------------------------------------
def test_shipping_line_from_name():
    assert shipping_line("MSC SINDY") == ("MSC", "MSC")
    assert shipping_line("CMA CGM GEMINI") == ("CMA CGM", "CMA CGM")
    assert shipping_line("MADRID MAERSK")[0] == "Maersk"           # line's word at the end
    assert shipping_line("EVER GREET")[0] == "Evergreen"
    assert shipping_line("HAMBURG EXPRESS")[0] == "Hapag-Lloyd"
    assert shipping_line("EVERGREEN SPIRIT") is None              # whole words only
    assert shipping_line("MSC") is None                           # the line's word alone is not a ship name
    assert shipping_line("RIX TANGO") is None
    assert shipping_line(None) is None


def test_shipping_line_ignores_punctuation_and_hyphens():
    assert shipping_line("MAERSK-SEOUL")[0] == "Maersk"
    assert shipping_line("HAMBURG-EXPRESS")[0] == "Hapag-Lloyd"
    assert shipping_line("MSC.SINDY")[0] == "MSC"
    assert shipping_line("X-PRESS MULHACEN")[0] == "X-Press Feeders"
    assert shipping_line("X PRESS MULHACEN")[0] == "X-Press Feeders"


def test_is_cargo_type():
    assert is_cargo_type(70) is True and is_cargo_type(79) is True and is_cargo_type("74") is True
    assert is_cargo_type(52) is False and is_cargo_type(80) is False
    assert is_cargo_type(None) is None and is_cargo_type(0) is None      # 0 = "not reported"
    assert is_cargo_type("abc") is None


def test_is_moored_has_two_separate_triggers():
    assert is_moored({"nav_status": 5, "sog": 3.0})        # says "moored", even if speed looks odd
    assert is_moored({"nav_status": 0, "sog": 0.2})        # not moving
    assert not is_moored({"nav_status": 0, "sog": 8.0})
    assert not is_moored({"nav_status": 0, "sog": None})


def test_container_terminal_areas():
    assert container_terminal(53.5399, 9.9070) == "Waltershof (Burchardkai / Eurogate)"   # where MSC SINDY moored
    assert container_terminal(53.505, 9.930) == "Altenwerder (CTA)"
    assert container_terminal(54.15, 7.47) is None                                       # out in the North Sea
    assert container_terminal(None, None) is None


def test_container_guess_rules():
    tug = container_guess(ship(name="MSC HELPER", ship_type=52))
    assert tug["label"].startswith(CONTAINER_UNLIKELY) and not tug["likely"]   # not cargo, even with a line's name

    by_name = container_guess(ship(name="MAERSK SEOUL", ship_type=74))
    assert by_name["label"] == f"{CONTAINER_LIKELY} · name"           # the table shows which clue (name/berth)
    assert by_name["verdict"] == CONTAINER_LIKELY
    assert by_name["likely"] and by_name["line"] == "Maersk"

    at_terminal = container_guess(ship(name="BIANCA RAMBOW", ship_type=79, lat=53.5321, lon=9.9087,
                                       sog=0, nav_status=5))
    assert at_terminal["label"] == f"{CONTAINER_LIKELY} · berth Waltershof"
    assert at_terminal["likely"] and at_terminal["line"] is None             # a berth never gives the line

    sailing_past = ship(name="BIANCA RAMBOW", ship_type=79, lat=53.5321, lon=9.9087, sog=8.0, nav_status=0)
    assert container_guess(sailing_past)["label"] == CONTAINER_UNKNOWN       # only moored ships count

    assert container_guess(ship(name="RIX TANGO", ship_type=70))["label"] == CONTAINER_UNKNOWN
    row = assess_ship(ship(name="MSC SINDY", ship_type=71, eta=eta_in(33)), NOW)
    assert row["Shipping line"] == "MSC" and row["container_likely"] is True


def test_unknown_type_ship_at_terminal_counts():
    feeder = container_guess(ship(name="SMALL FEEDER", ship_type=None, lat=53.505, lon=9.930, sog=0, nav_status=5))
    assert feeder["likely"] and "no reported type" in feeder["reason"]


def test_weak_words_need_a_cargo_type():
    assert container_guess(ship(name="POLAR EXPRESS", ship_type=None))["label"] == CONTAINER_UNKNOWN
    assert container_guess(ship(name="ONE WORLD", ship_type=None))["label"] == CONTAINER_UNKNOWN
    assert container_guess(ship(name="HAMBURG EXPRESS", ship_type=71))["line"] == "Hapag-Lloyd"
    assert container_guess(ship(name="MSC MARIE", ship_type=None))["line"] == "MSC"   # strong words still count


# ---------------------------------------------------------------------------
# Security: the collector must clean untrusted radio data
# ---------------------------------------------------------------------------
def test_collector_cleans_untrusted_data():
    ships = {}
    handle_message(ships, {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": "211000001"},
        "Message": {"ShipStaticData": {
            "Name": "<script>alert(1)</script>LONGER THAN TWENTY CHARACTERS",
            "Destination": "deham\x1b[31m\n",
            "Type": "not a number",
            "ImoNumber": True,
            "Eta": {"Month": "11", "Day": 2, "Hour": "evil", "Minute": 0, "Extra": "dropped"},
        }},
    })
    s = ships["211000001"]
    # "<" and "[" are real AIS characters, so they are kept here; app.py escapes them when showing them.
    assert s["name"] == "<SCRIPT>ALERT(1)</SC"          # cut to the AIS maximum of 20 characters
    assert s["destination"] == "DEHAM[31M"              # the invisible control character (ESC) and newline are gone
    assert s["ship_type"] is None and s["imo"] is None  # bad numbers become "unknown"
    assert s["eta"] == {"Month": 11, "Day": 2, "Hour": 0, "Minute": 0}

    # Messages that are not what AISStream normally sends are ignored, not crashed on.
    handle_message(ships, ["not", "a", "dict"])
    handle_message(ships, {"MessageType": "PositionReport", "MetaData": {"MMSI": "x"}, "Message": {}})
    handle_message(ships, {"MessageType": "PositionReport", "MetaData": {"MMSI": 211000002},
                           "Message": {"PositionReport": {"Latitude": "NaN", "Longitude": 5}}})
    assert set(ships) <= {"211000001", "211000002"}     # no ship was created from the bad MMSI "x"
    assert "lat" not in ships.get("211000002", {})       # a "NaN" position is never saved


def test_old_saved_records_are_cleaned_when_loaded(tmp_path, monkeypatch):
    # A file saved before the safety checks existed: messy name, text ship type, impossible ETA.
    import json
    import collector
    import config
    old = {"meta": {}, "ships": {
        "211000003": {"mmsi": "211000003", "name": "hhla  i i i", "destination": "deham", "ship_type": "seventy",
                      "lat": 53.54, "lon": 9.97, "sog": 102.3, "cog": 360,
                      "eta": {"Month": 45, "Day": 50, "Hour": 24, "Minute": 60}},
        "bad": {"mmsi": "bad", "lat": "nowhere", "lon": 1},
    }}
    path = tmp_path / "ships.json"
    path.write_text(json.dumps(old))
    monkeypatch.setattr(config, "LIVE_DATA_FILE", path)

    ships = collector.load_store()
    assert set(ships) == {"211000003"}                    # the record without a real position is dropped
    s = ships["211000003"]
    assert s["name"] == "HHLA I I I" and s["destination"] == "DEHAM"
    assert s["ship_type"] is None
    assert s["sog"] is None and s["cog"] is None          # 102.3 and 360 mean "not available" in AIS
    assert s["eta"] == {"Month": 0, "Day": 0, "Hour": 24, "Minute": 60}   # impossible month/day -> "not set"


# ---------------------------------------------------------------------------
# Arrival words from GLOSSARY.md: Arrived, Arriving, Waiting, In another port
# ---------------------------------------------------------------------------
def test_arrived_means_moored_in_hamburg():
    moored = assess_ship(ship(lat=53.5399, lon=9.9070, sog=0, nav_status=5, eta=eta_in(1)), NOW)
    assert moored["Flag"] == "🔵" and moored["Status"] == "Arrived"
    approaching = assess_ship(ship(lat=53.55, lon=9.85, sog=8.0, nav_status=0, eta=eta_in(1)), NOW)
    assert approaching["Status"] == "Arriving"


def test_moored_in_another_port_is_not_waiting():
    rotterdam = assess_ship(ship(lat=51.95, lon=4.05, sog=0, nav_status=5, eta=eta_in(30)), NOW)
    assert rotterdam["Flag"] == "⚫" and rotterdam["Status"] == "In another port"
    at_anchor = assess_ship(ship(lat=54.0, lon=7.5, sog=0.2, nav_status=1, eta=eta_in(30)), NOW)
    assert at_anchor["Flag"] == "🟡" and at_anchor["Status"] == "Waiting"
    drifting = assess_ship(ship(lat=54.0, lon=7.5, sog=0.3, nav_status=0, eta=eta_in(30)), NOW)
    assert drifting["Status"] == "Waiting"


def test_eastern_port_and_upper_elbe_are_on_the_elbe():
    # These ships are in Hamburg, not 150 nm away in the North Sea (bug found while writing GLOSSARY.md).
    assert sea_area(53.53, 10.06) == "Elbe river"      # eastern part of the Port of Hamburg
    assert sea_area(53.43, 10.34) == "Elbe river"      # upper Elbe, inland ships coming downriver
    assert sea_area(53.87, 10.70) == "Baltic / Kattegat"   # Lübeck stays in the Baltic
    in_port = assess_ship(ship(lat=53.53, lon=10.06, sog=0, nav_status=5), NOW)
    assert in_port["Status"] == "Arrived" and in_port["Distance (nm)"] < 15


def test_values_handed_to_the_ml_model():
    row = assess_ship(ship(eta=eta_in(33)), NOW)                  # sailing in the Channel at 16 kn
    assert row["calc_hours"] > 0 and row["stopped"] is False
    expected = NOW + timedelta(hours=row["calc_hours"])        # counted from the last position, not from now
    assert abs((row["calc_eta_utc"] - expected).total_seconds()) < 60   # calc_hours is rounded to 2 decimals
    waiting = assess_ship(ship(sog=0.2, nav_status=1, eta=eta_in(30)), NOW)
    assert waiting["stopped"] is True
