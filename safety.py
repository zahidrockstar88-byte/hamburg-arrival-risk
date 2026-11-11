"""
safety.py - Cleans data we do not control before we save or show it.

Why this file exists: ship names, destinations and call signs are typed by
crews and broadcast by radio. Anyone with a transmitter can send any text.
So we treat everything that comes from AIS as UNTRUSTED:

  1. When collecting (collector.py): keep only the characters AIS allows,
     cut text to its official maximum length, and turn numbers into real numbers.
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


def clean_ais_text(value, field: str = "name") -> str:
    """Return safe AIS text: allowed characters only, single spaces, official max length."""
    if not isinstance(value, str):
        return ""
    text = value.upper().replace("@", " ")        # "@" is AIS padding, not a real character
    text = _AIS_ALLOWED.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[: MAX_LEN.get(field, 20)].strip()


def to_int(value, low: int | None = None, high: int | None = None) -> int | None:
    """Turn a value into a whole number, or None if it is missing, not a number, or out of range."""
    if isinstance(value, bool):                    # True/False are not real numbers here
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def to_float(value, low: float | None = None, high: float | None = None) -> float | None:
    """Like to_int, but for decimal numbers (speed, course, position)."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:                           # "not a number" (NaN) is never equal to itself
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


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
