"""
config.py - All settings for the project in one place.

You can change the numbers here without touching the rest of the code.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Files and folders
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
LIVE_DATA_FILE = DATA_DIR / "ships.json"        # written by collector.py
RISK_ZONES_FILE = PROJECT_DIR / "risk_zones.json"  # chokepoint notes you update by hand

# ---------------------------------------------------------------------------
# Live ship data (AISStream.io)
# ---------------------------------------------------------------------------
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

# The area we listen to: from West Africa / Canary Islands up to Norway,
# and from the mid-Atlantic to Italy. Format: [[lat, lon], [lat, lon]].
# Ships outside this box are not seen.
BOUNDING_BOXES = [[[20.0, -30.0], [62.0, 16.0]]]

# How long one collector run listens before saving and stopping (minutes).
# Ships send their destination and ETA only every ~6 minutes,
# so runs shorter than ~10 minutes miss many ships.
DEFAULT_RUN_MINUTES = 15

# Forget ships we have not heard from in this many hours.
FORGET_AFTER_HOURS = 72

# ---------------------------------------------------------------------------
# Hamburg and the sea route to it
# ---------------------------------------------------------------------------
HAMBURG = (53.54, 9.97)          # Port of Hamburg (lat, lon)
ELBE_ENTRANCE = (54.00, 8.10)    # "Elbe 1" - where the river trip starts

# Waypoints ships pass on the way to the Elbe.
# The code picks the ones that are still ahead of the ship.
WAYPOINTS = {
    "Gibraltar": (35.95, -5.60),
    "Cape Finisterre": (43.20, -9.80),
    "Ushant": (48.60, -5.40),
    "Dover Strait": (51.00, 1.50),
    "Elbe entrance": ELBE_ENTRANCE,
    "Kiel Canal (east end)": (54.37, 10.15),
    "Kiel Canal (west end)": (53.89, 9.14),
}

# River Elbe: about 75 nautical miles from Elbe 1 to Hamburg.
# Ships go slower there (speed limits, pilots, tide).
ELBE_RIVER_SPEED_KN = 10.0
PILOT_AND_BERTH_BUFFER_HOURS = 1.0

# ---------------------------------------------------------------------------
# Risk flag rules
# ---------------------------------------------------------------------------
# If the calculated ETA is this many hours later than the ship's own ETA,
# we flag it as "likely late".
LATE_THRESHOLD_HOURS = 12

# If we have no new position for this long, we can't trust the data.
STALE_AFTER_HOURS = 24

# Speed used when a ship is stopped or its speed looks wrong (knots).
TYPICAL_SPEED_KN = 14.0

# Speeds outside this range are treated as unreliable (knots).
MIN_VALID_SPEED_KN = 3.0
MAX_VALID_SPEED_KN = 26.0

# A ship this close to Hamburg counts as arriving (nautical miles).
ARRIVED_WITHIN_NM = 15

# ---------------------------------------------------------------------------
# Container ships and shipping lines
# ---------------------------------------------------------------------------
# AIS does NOT say what a ship carries. Container ships report as ordinary
# cargo ships (type 70-79). So we make an educated guess in two ways:
#
# 1. The ship's name. Most big container ships are named after the shipping
#    line (carrier) that runs them: "MSC SINDY", "MAERSK SEOUL", "EVER GREET".
#    Format: (where the word must be, the word, the shipping line's name)
#    "start" = first word(s) of the name, "end" = last word(s) of the name.
SHIPPING_LINE_NAMES = [
    ("start", "MSC", "MSC"),
    ("start", "MAERSK", "Maersk"),
    ("end", "MAERSK", "Maersk"),            # e.g. "MADRID MAERSK"
    ("start", "CMA CGM", "CMA CGM"),
    ("start", "APL", "CMA CGM (APL)"),
    ("start", "COSCO", "COSCO Shipping"),
    ("start", "CSCL", "COSCO Shipping"),
    ("start", "OOCL", "OOCL (COSCO group)"),
    ("start", "EVER", "Evergreen"),
    ("start", "ONE", "Ocean Network Express (ONE)"),
    ("end", "EXPRESS", "Hapag-Lloyd"),      # e.g. "HAMBURG EXPRESS"; a guess, other ships use this word too
    ("start", "HMM", "HMM"),
    ("start", "YM", "Yang Ming"),
    ("start", "ZIM", "ZIM"),
    ("start", "WAN HAI", "Wan Hai"),
    ("start", "X-PRESS", "X-Press Feeders"),
    ("start", "KOTA", "PIL"),
]

# Words that other ships use too ("POLAR EXPRESS", "ONE WORLD"). They only count
# when the ship has also reported a cargo ship type (70-79), not when the type is unknown.
WEAK_LINE_WORDS = {"EXPRESS", "ONE"}

# 2. Where the ship is moored. A cargo ship moored at a container terminal is
#    almost certainly a container ship. Boxes are APPROXIMATE:
#    ((south lat, west lon), (north lat, east lon)).
CONTAINER_TERMINALS = {
    "Waltershof (Burchardkai / Eurogate)": ((53.525, 9.880), (53.548, 9.935)),
    "Altenwerder (CTA)": ((53.495, 9.915), (53.515, 9.945)),
    "Tollerort (CTT)": ((53.538, 9.935), (53.548, 9.960)),
}
