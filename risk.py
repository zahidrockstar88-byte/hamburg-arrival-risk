"""
risk.py - The "brain" of the project.

For every ship heading to Hamburg it answers three questions:
  1. How far is the ship from Hamburg, following the real sea route?
  2. When will it arrive if it keeps its current speed? (the "calculated ETA")
  3. Is the ship's own ETA realistic, or is it likely to be late?

No live data is needed to use this file. collector.py feeds it live data,
app.py shows the results.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

import config

# ---------------------------------------------------------------------------
# 1. Is the ship going to Hamburg?
# ---------------------------------------------------------------------------
# Crews type the destination by hand, so it can look like:
#   "HAMBURG", "DEHAM", "DE HAM", "NLRTM>DEHAM", "HAMBURG GERMANY", "DE HAM OPL"
# "DEHAM" is the official UN/LOCODE for Hamburg.
# "A>B" means "from A to B", so we only look at the part after the last ">".

HAMBURG_PATTERNS = ("DEHAM", "HAMBURG", "HAMBURGO", "HAMBOURG")


def final_destination(raw: str | None) -> str:
    """Return the cleaned final destination text (the part after the last '>')."""
    if not raw:
        return ""
    text = raw.upper().strip()
    if ">" in text:
        text = text.split(">")[-1]
    return text.strip()


def is_bound_for_hamburg(raw: str | None) -> bool:
    """True if the destination the crew typed means Hamburg."""
    text = re.sub(r"[^A-Z]", "", final_destination(raw))  # drop spaces, dots, dashes
    return any(pattern in text for pattern in HAMBURG_PATTERNS)


# ---------------------------------------------------------------------------
# 2. Distances
# ---------------------------------------------------------------------------
EARTH_RADIUS_NM = 3440.065  # Earth's radius in nautical miles


def distance_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line ('great circle') distance between two points, in nautical miles."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# 3. Where is the ship? (rough sea areas, good enough for routing)
# ---------------------------------------------------------------------------
def sea_area(lat: float, lon: float) -> str:
    """Name the sea area a position is in."""
    if 53.35 <= lat <= 54.05 and 8.1 <= lon <= 10.05:
        return "Elbe river"
    if lon > 10.2 and lat > 53.8:
        return "Baltic / Kattegat"
    if lat > 57.0 and 7.5 < lon <= 10.2:
        return "Skagerrak"
    if 30 <= lat <= 44.5 and -5.4 <= lon <= 16 and not (lat > 43.3 and lon < 3):
        return "Mediterranean"
    if lat < 34 and lon < -8:
        return "Off West Africa"
    if lat < 43.3 and lon < -5.4:
        return "Off Portugal / Spain"
    if 43.3 <= lat < 48.7 and lon < -1.0:
        return "Bay of Biscay"
    if lat >= 48.7 and lon < -5.6:
        return "Atlantic, west of the Channel"
    if 48.5 <= lat <= 51.3 and -5.6 <= lon < 1.5:
        return "English Channel"
    return "North Sea"


# The waypoints still ahead of a ship, depending on where it is now.
ROUTES_FROM_AREA = {
    "Off West Africa": ["Cape Finisterre", "Ushant", "Dover Strait", "Elbe entrance"],
    "Mediterranean": ["Gibraltar", "Cape Finisterre", "Ushant", "Dover Strait", "Elbe entrance"],
    "Off Portugal / Spain": ["Cape Finisterre", "Ushant", "Dover Strait", "Elbe entrance"],
    "Bay of Biscay": ["Ushant", "Dover Strait", "Elbe entrance"],
    "Atlantic, west of the Channel": ["Channel entrance", "Dover Strait", "Elbe entrance"],
    "English Channel": ["Dover Strait", "Elbe entrance"],
    "North Sea": ["Elbe entrance"],
    "Skagerrak": ["Hanstholm", "Elbe entrance"],
}

EXTRA_WAYPOINTS = {
    "Channel entrance": (49.80, -5.80),
    "Hanstholm": (57.30, 7.90),
}

KIEL_CANAL_SPEED_KN = 8.0
RIVER_WINDING_FACTOR = 1.05  # the river bends, so it is a bit longer than a straight line


def _point(name: str) -> tuple[float, float]:
    return config.WAYPOINTS.get(name) or EXTRA_WAYPOINTS[name]


def route_to_hamburg(lat: float, lon: float) -> dict:
    """
    Distance still to go, split into parts that are sailed at different speeds:
      sea_nm   - open sea, sailed at the ship's own speed
      slow_nm  - River Elbe (and Kiel Canal), sailed at a fixed low speed
    """
    area = sea_area(lat, lon)
    here = (lat, lon)

    if area == "Elbe river":
        river = distance_nm(here, config.HAMBURG) * RIVER_WINDING_FACTOR
        return {"area": area, "sea_nm": 0.0, "slow_nm": river, "slow_hours": river / config.ELBE_RIVER_SPEED_KN,
                "via": ["River Elbe"]}

    if area == "Baltic / Kattegat":
        kiel_east, kiel_west = _point("Kiel Canal (east end)"), _point("Kiel Canal (west end)")
        sea = distance_nm(here, kiel_east)
        canal = distance_nm(kiel_east, kiel_west) * 1.3   # the canal is not straight
        river = distance_nm(kiel_west, config.HAMBURG) * RIVER_WINDING_FACTOR
        hours = canal / KIEL_CANAL_SPEED_KN + river / config.ELBE_RIVER_SPEED_KN
        return {"area": area, "sea_nm": sea, "slow_nm": canal + river, "slow_hours": hours,
                "via": ["Kiel Canal", "River Elbe"]}

    # Everything else: sail waypoint to waypoint until the Elbe entrance, then up the river.
    via = ROUTES_FROM_AREA.get(area, ["Elbe entrance"])
    sea, previous = 0.0, here
    for name in via:
        nxt = _point(name)
        sea += distance_nm(previous, nxt)
        previous = nxt
    river = distance_nm(config.ELBE_ENTRANCE, config.HAMBURG) * RIVER_WINDING_FACTOR
    return {"area": area, "sea_nm": sea, "slow_nm": river, "slow_hours": river / config.ELBE_RIVER_SPEED_KN,
            "via": via[:-1] + ["River Elbe"]}


# ---------------------------------------------------------------------------
# 4. Times
# ---------------------------------------------------------------------------
def parse_time(value: str | None) -> datetime | None:
    """Read a time saved by the collector (ISO format, UTC)."""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def parse_ais_eta(eta: dict | None, now: datetime) -> datetime | None:
    """
    Ships send their ETA as month/day/hour/minute in UTC, with NO year.
    Month 0 or day 0 means "not set". We guess the year that makes sense:
    an ETA in January seen in December belongs to next year.
    """
    if not eta:
        return None
    month, day = int(eta.get("Month", 0) or 0), int(eta.get("Day", 0) or 0)
    hour, minute = int(eta.get("Hour", 24) or 0), int(eta.get("Minute", 60) or 0)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    hour = 0 if hour >= 24 else hour
    minute = 0 if minute >= 60 else minute

    for year in (now.year, now.year + 1, now.year - 1):
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:          # e.g. 31 February
            return None
        if now - timedelta(days=60) <= candidate <= now + timedelta(days=300):
            return candidate
    return None


def nice_time(t: datetime | None) -> str:
    return t.strftime("%a %d %b, %H:%M UTC") if t else "—"


# ---------------------------------------------------------------------------
# 5. Where did the ship come from? (based on where we first saw it)
# ---------------------------------------------------------------------------
def route_note(ship: dict) -> str:
    if ship.get("seen_off_west_africa"):
        return ("Came up from the South Atlantic: likely the Cape of Good Hope route "
                "(or from West Africa / South America).")
    if ship.get("seen_in_mediterranean"):
        return "Came through the Mediterranean: Suez Canal route or a Mediterranean port."
    return "Earlier route unknown (first seen close to northern Europe)."


# ---------------------------------------------------------------------------
# 6. Is it a container ship, and which shipping line runs it?
# ---------------------------------------------------------------------------
# AIS only says "cargo ship" (type 70-79). It does not say what is on board,
# and it never says who owns the containers or the cargo (that is in the
# confidential bill of lading). So this is an educated GUESS, and we say so.

# The three answers "Container ship?" can give. One place, so the app and the tests use the same words.
CONTAINER_LIKELY = "Likely"
CONTAINER_UNKNOWN = "Unknown"
CONTAINER_UNLIKELY = "Unlikely"


def _name_words(name: str | None) -> list[str]:
    """
    Split a ship name into words. Dots, hyphens and other symbols count as spaces:
    'CMA CGM  GEMINI' -> ['CMA', 'CGM', 'GEMINI'],  'MAERSK-SEOUL' -> ['MAERSK', 'SEOUL'].
    """
    return re.sub(r"[^A-Z0-9]", " ", (name or "").upper()).split()


def shipping_line(name: str | None) -> tuple[str, str] | None:
    """
    Guess the shipping line from the ship's name.
    Returns (line name, matched word) or None. Whole words only, so "EVERGREEN" does not match "EVER".
    """
    words = _name_words(name)
    for position, word, line_name in config.SHIPPING_LINE_NAMES:
        pattern = _name_words(word)               # "X-PRESS" -> ["X", "PRESS"], same rule as the name
        if len(words) <= len(pattern):            # the name must have something besides the line's word
            continue
        name_part = words[: len(pattern)] if position == "start" else words[-len(pattern):]
        if name_part == pattern:
            return line_name, word
    return None


def container_terminal(lat: float | None, lon: float | None) -> str | None:
    """Name of the Hamburg container terminal at this position, or None."""
    if lat is None or lon is None:
        return None
    for terminal, ((south, west), (north, east)) in config.CONTAINER_TERMINALS.items():
        if south <= lat <= north and west <= lon <= east:
            return terminal
    return None


def is_cargo_type(ship_type) -> bool | None:
    """True for AIS cargo types 70-79, False for other known types, None if unknown."""
    if ship_type in (None, 0):
        return None
    try:
        return 70 <= int(ship_type) <= 79
    except (TypeError, ValueError):
        return None


def is_moored(ship: dict) -> bool:
    """True if the ship says it is moored (AIS status 5) or is not moving (under 0.5 knots)."""
    sog = ship.get("sog")
    return ship.get("nav_status") == 5 or (sog is not None and sog < 0.5)


def container_guess(ship: dict) -> dict:
    """
    Decide 'Container ship?' for one ship, with the reason, in plain words.
    Rules, first match wins:
      1. Reported type is not cargo (tug, ferry, tanker...)       -> Unlikely
      2. Name starts/ends with a container line's word            -> Likely (line from the name)
         (weak words like EXPRESS only count for reported cargo types)
      3. Cargo or unknown-type ship moored at a container terminal -> Likely (line unknown)
      4. Anything else                                             -> Unknown
    Returns: label (shown in the table), likely (True/False), line (or None), reason.
    """
    cargo = is_cargo_type(ship.get("ship_type"))
    match = shipping_line(ship.get("name"))

    if cargo is False:
        return {"label": f"{CONTAINER_UNLIKELY} · type {ship.get('ship_type')}", "likely": False, "line": None,
                "reason": f"The ship reports AIS type {ship.get('ship_type')}, which is not a cargo ship. "
                          "Crews set this type themselves, so it can be wrong."}

    if match:
        line_name, matched_word = match
        if matched_word not in config.WEAK_LINE_WORDS or cargo is True:
            return {"label": f"{CONTAINER_LIKELY} · name", "likely": True, "line": line_name,
                    "reason": f"The name contains \"{matched_word}\", a word used by {line_name} container ships."}

    terminal = container_terminal(ship.get("lat"), ship.get("lon"))
    if terminal and is_moored(ship):
        kind = "Cargo ship" if cargo else "Ship with no reported type"
        return {"label": f"{CONTAINER_LIKELY} · berth {terminal.split(' (')[0]}", "likely": True, "line": None,
                "reason": f"{kind} moored at the {terminal} container terminal. "
                          "The berth does not tell us the shipping line."}

    return {"label": CONTAINER_UNKNOWN, "likely": False, "line": None,
            "reason": "AIS does not say what a ship carries, and neither the name nor the berth gives a clue."}


# ---------------------------------------------------------------------------
# 7. The main check: one row of results per ship
# ---------------------------------------------------------------------------
FLAG_ORDER = {"🔴": 0, "🟡": 1, "🟢": 2, "⚪": 3}


def assess_ship(ship: dict, now: datetime | None = None, settings: dict | None = None) -> dict:
    """Run all checks on one ship and return one row for the dashboard table."""
    now = now or datetime.now(timezone.utc)
    s = {
        "late_threshold_h": config.LATE_THRESHOLD_HOURS,
        "stale_after_h": config.STALE_AFTER_HOURS,
        **(settings or {}),
    }

    lat, lon = ship["lat"], ship["lon"]
    last_seen = parse_time(ship.get("last_position_utc")) or now
    age_h = max(0.0, (now - last_seen).total_seconds() / 3600)
    route = route_to_hamburg(lat, lon)
    total_nm = route["sea_nm"] + route["slow_nm"]

    # --- Which speed do we trust? ---
    sog = ship.get("sog")
    stopped = (sog is not None and sog < 1.0) or ship.get("nav_status") in (1, 5)   # 1 = at anchor, 5 = moored
    if sog is not None and config.MIN_VALID_SPEED_KN <= sog <= config.MAX_VALID_SPEED_KN:
        speed, speed_note = sog, "current speed"
    else:
        speed, speed_note = config.TYPICAL_SPEED_KN, "typical speed (current speed not usable)"

    # --- Calculated ETA: from the time of the last position, not from now ---
    hours_to_go = route["sea_nm"] / speed + route["slow_hours"] + config.PILOT_AND_BERTH_BUFFER_HOURS
    calc_eta = last_seen + timedelta(hours=hours_to_go)
    reported_eta = parse_ais_eta(ship.get("eta"), now)
    delay_h = (calc_eta - reported_eta).total_seconds() / 3600 if reported_eta else None

    # --- Decide the flag (first rule that matches wins) ---
    if total_nm <= config.ARRIVED_WITHIN_NM or (route["area"] == "Elbe river" and ship.get("nav_status") == 5):
        flag, label, reason = "⚪", "Arriving", "Ship is in or very close to the port of Hamburg."
    elif age_h > s["stale_after_h"]:
        flag, label = "🟡", "Data too old"
        reason = f"Last position is {age_h:.0f} h old. The ship may have left our receiver range."
    elif stopped:
        flag, label = "🟡", "Stopped"
        reason = ("Ship is stopped or at anchor. It may be waiting for a berth, the tide or a pilot, "
                  "so add waiting time to any ETA.")
    elif reported_eta is None:
        flag, label = "🟡", "No ETA sent"
        reason = "The crew has not entered a valid ETA, so we can't compare."
    elif reported_eta < now and total_nm > 50:
        flag, label = "🔴", "ETA already passed"
        reason = f"The ship's ETA has passed but it is still {total_nm:.0f} nm away."
    elif delay_h > s["late_threshold_h"]:
        flag, label = "🔴", f"Likely late (~{delay_h:.0f} h)"
        reason = (f"At {speed:.1f} kn it needs {hours_to_go:.0f} h for {total_nm:.0f} nm. "
                  f"That is {delay_h:.0f} h later than the ETA the crew reported.")
    elif delay_h < -2 * s["late_threshold_h"]:
        flag, label = "🟢", "On track (may be early)"
        reason = (f"At {speed:.1f} kn it could arrive {abs(delay_h):.0f} h before its reported ETA. "
                  "It may slow down to save fuel or match its berth window.")
    else:
        flag, label = "🟢", "On track"
        reason = f"Reported ETA fits the distance at {speed:.1f} kn (difference {delay_h:+.0f} h)."

    container = container_guess(ship)

    return {
        "Flag": flag,
        "Status": label,
        "Ship": ship.get("name") or f"MMSI {ship.get('mmsi')}",
        "Container ship?": container["label"],
        "Shipping line": container["line"] or "—",
        "Container reason": container["reason"],
        "container_likely": container["likely"],
        "calc_hours": round(hours_to_go, 2),      # used by the experimental ML estimate (eta_model.py)
        "stopped": bool(stopped),
        "calc_eta_utc": calc_eta,
        "Where": route["area"],
        "Distance (nm)": round(total_nm),
        "Speed (kn)": round(sog, 1) if sog is not None else None,
        "Reported ETA": nice_time(reported_eta),
        "Calculated ETA": nice_time(calc_eta),
        "Difference (h)": round(delay_h) if delay_h is not None else None,
        "Why": reason,
        "Route note": route_note(ship),
        "Route ahead": " → ".join(route["via"]),
        "Speed used": speed_note,
        "Position age (h)": round(age_h, 1),
        "Destination typed": ship.get("destination", ""),
        "MMSI": ship.get("mmsi"),
        "IMO": ship.get("imo") or None,
        "lat": lat,
        "lon": lon,
        "_sort": (FLAG_ORDER.get(flag, 9), -(delay_h or 0)),
    }


def assess_all(ships: list[dict], now: datetime | None = None, settings: dict | None = None) -> list[dict]:
    rows = [assess_ship(s, now, settings) for s in ships if s.get("lat") is not None]
    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        r.pop("_sort")
    return rows
