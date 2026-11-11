"""
safety.py - Cleans data we do not control before we save or show it.

Why this file exists: ship names, destinations and call signs are typed by
crews and broadcast by radio. Anyone with a transmitter can send any text.
So we treat everything that comes from AIS as UNTRUSTED:

  1. When collecting (collector.py) AND when loading saved data (app.py):
     keep only the characters AIS allows, cut text to its official maximum
     length, and turn numbers into real numbers inside their valid range.
  2. When showing it (app.py): escape the text, so a name like
     "[CLICK](HTTP://X.CO)" is shown as plain text, not turned into a link.
"""

from __future__ import annotations

import re

# AIS text uses a small alphabet ("6-bit ASCII"): capital letters, digits,
# space and a few symbols. Anything else cannot be real AIS text.
_AIS_ALLOWED = re.compile(r"[^A-Z0-9 !\"#$%&'()*+,\-./:;<=>?@\[\\\]^_]")

# Maximum lengths from the AIS standard (ITU-R M.1371).
MAX_LEN = {"name": 20, "destination": 20, "callsign": 7}


def clean_plain_text(value, max_length: int) -> str:
    """Any outside text as one plain line: no invisible control characters, single spaces, limited length."""
    if not isinstance(value, str):
        return ""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length].strip()


def clean_ais_text(value, field: str = "name") -> str:
    """Return safe AIS text: allowed characters only, single spaces, official max length."""
    if not isinstance(value, str):
        return ""
    text = value.upper().replace("@", " ")        # "@" is AIS padding, not a real character
    text = _AIS_ALLOWED.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[: MAX_LEN.get(field, 20)].strip()


def _number(value, convert, low, high):
    """Shared check for to_int and to_float: convert, then make sure it is a real number in range."""
    if isinstance(value, bool):                    # True/False are not real numbers here
        return None
    try:
        number = convert(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number:                           # "not a number" (NaN) is never equal to itself
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def to_int(value, low: int | None = None, high: int | None = None) -> int | None:
    """Turn a value into a whole number, or None if it is missing, not a number, or out of range."""
    return _number(value, int, low, high)


def to_float(value, low: float | None = None, high: float | None = None) -> float | None:
    """Like to_int, but for decimal numbers (speed, course, position)."""
    return _number(value, float, low, high)


# Valid ranges from the AIS standard. Values just outside these are AIS codes
# for "not available" (for example speed 102.3, course 360, hour 24, minute 60).
ETA_RANGES = {"Month": (0, 12), "Day": (0, 31), "Hour": (0, 24), "Minute": (0, 60)}   # 0 / 24 / 60 = "not set"
SPEED_RANGE = (0, 102.2)       # knots; 102.3 means "not available"
COURSE_RANGE = (0, 359.9)      # degrees; 360 means "not available"


def clean_eta(eta) -> dict | None:
    """Keep only the four ETA numbers, each in its valid range. A bad number becomes 0 ("not set")."""
    if not isinstance(eta, dict):
        return None
    return {key: to_int(eta.get(key), low, high) or 0 for key, (low, high) in ETA_RANGES.items()}


def clean_saved_ship(ship) -> dict | None:
    """
    Check one ship record loaded from data/ships.json (it may have been saved by an
    older version of the collector, before these checks existed). Returns a clean
    copy, or None if the record has no usable position.
    """
    if not isinstance(ship, dict):
        return None
    lat, lon = to_float(ship.get("lat"), -90, 90), to_float(ship.get("lon"), -180, 180)
    if lat is None or lon is None:
        return None
    clean = dict(ship)
    clean.update({
        "mmsi": str(to_int(ship.get("mmsi"), 1, 999_999_999) or ""),
        "name": clean_ais_text(ship.get("name"), "name"),
        "destination": clean_ais_text(ship.get("destination"), "destination"),
        "callsign": clean_ais_text(ship.get("callsign"), "callsign"),
        "lat": lat,
        "lon": lon,
        "sog": to_float(ship.get("sog"), *SPEED_RANGE),
        "cog": to_float(ship.get("cog"), *COURSE_RANGE),
        "nav_status": to_int(ship.get("nav_status"), 0, 15),
        "ship_type": to_int(ship.get("ship_type"), 0, 99),
        "imo": to_int(ship.get("imo"), 1, 9_999_999),
        "draught_m": to_float(ship.get("draught_m"), 0, 25.5),
        "length_m": to_int(ship.get("length_m"), 20, 460),
        "eta": clean_eta(ship.get("eta")),
    })
    return clean


# Characters that change how Markdown (Streamlit's text formatting) looks.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~:$])")


def md(value) -> str:
    """Escape text before putting it into st.markdown, so it can never become a link, image or formatting."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", str(value if value is not None else ""))


def safe_link(url) -> str | None:
    """Only allow normal https:// web links (blocks javascript: and other tricks)."""
    if isinstance(url, str) and re.fullmatch(r"https://[A-Za-z0-9.\-]+(/[^\s()<>\[\]]*)?", url.strip()):
        return url.strip()
    return None
