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

# ---------------------------------------------------------------------------
# Carrier reliability (procurement view)
# ---------------------------------------------------------------------------
# A ship is "on time" if it berthed within this many hours of the ETA it first reported to us.
# 24 h (one day either way) is the usual industry tolerance for schedule reliability.
ON_TIME_TOLERANCE_HOURS = 24
# Below this many arrivals a carrier's percentage is not shown: too few to mean anything.
MIN_ARRIVALS_FOR_SCORE = 3

# ---------------------------------------------------------------------------
# After the berth: unloading and pickup (all ranges are low, high)
# ---------------------------------------------------------------------------
# Ship size in TEU from its length (m). Rule of thumb from typical container-ship classes
# (feeder ~150 m / 1,000 TEU ... ultra-large ~400 m / 20,000+ TEU). Not a sourced table.
TEU_BY_LENGTH_M = [(120, 500), (150, 1000), (175, 1700), (200, 2500), (230, 3500), (260, 4500),
                   (300, 8000), (335, 10000), (366, 14000), (400, 20000)]
# No draught fallback on purpose: ships report their CURRENT draught, so a part-loaded ship looks too small.

# Hamburg is one stop in a loop of ports, so only part of the ship is unloaded here.
# Assumption (not sourced): 10-25 % of the ship's capacity is unloaded in Hamburg.
UNLOAD_SHARE_RANGE = (0.10, 0.25)
TEU_PER_MOVE = 1.65            # one crane move lifts ~1.65 TEU on average (mix of 20 ft and 40 ft boxes)

# Average number of quay cranes working one ship, by ship size (TEU, cranes). Assumption from typical deployment.
# A smooth average ("crane intensity"), not whole steps: terminals move cranes on and off during a call, and
# whole steps made a slightly bigger ship unload faster than a smaller one.
CRANE_INTENSITY_BY_TEU = [(1000, 2), (3000, 3), (8000, 4), (14000, 5), (20000, 6)]
# Moves per crane per hour. Top terminals reach ~40 (Port Technology berth productivity ranking);
# we use a lower, more typical range because no HHLA figure is published.
CRANE_MOVES_PER_HOUR = (25, 35)
# Ceiling for one ship: about 3,500 moves a day is a realistic maximum for an ultra-large ship
# in North Europe (Dynamar, via Seatrade Maritime).
MAX_MOVES_PER_SHIP_PER_HOUR = 3500 / 24

START_UNLOADING_AFTER_BERTH_H = (0.5, 1.5)   # mooring, lashing, gangway (assumption)
READY_FOR_PICKUP_AFTER_UNLOAD_H = (2, 6)     # stacking in the yard and release (assumption; customs pre-cleared)
RAIL_WAIT_FOR_TRAIN_H = (2, 12)             # trains leave the terminals several times a day (assumption)
TRUCK_SPEED_KMH = (30, 50)                   # average speed from the terminal, incl. port traffic (assumption)
TERMINAL_GATE_H = (0.5, 1.5)                 # truck gate-in, loading and gate-out (assumption)
DEFAULT_WAREHOUSE_KM = 30                    # a typical warehouse in the Hamburg area (changeable in the sidebar)

# ---------------------------------------------------------------------------
# Cost of delay (US dollars, because the charter indices are in dollars)
# ---------------------------------------------------------------------------
# Daily cost of the ship's time = its time-charter rate. A smooth line is drawn through these points
# (ship size in TEU, US$ per day), so there are no jumps between size bands.
# Sourced: New ConTex charter index, Aug-Oct 2026 (DynaLiners Sept 2026, Container News, VHBS):
#   1,700 TEU $33,877; 2,500 TEU $37,227-38,665 (mid $37,946); 2,700 TEU $40,052; 4,250 TEU $58,050-59,511 (mid $58,781).
SHIP_RATE_SOURCED = [(1700, 33877), (2500, 37946), (2700, 40052), (4250, 58781)]
SHIP_RATE_SOURCED_SPREAD = 0.05     # shown as +-5 % around the line
# ESTIMATE, not sourced: the index publishes nothing we could verify above 4,250 TEU. Bigger ships earn more
# per day, but less per TEU; these points continue that trend and are labelled "estimate" on the page.
SHIP_RATE_ESTIMATED = [(8000, 75000), (14000, 90000), (20000, 105000)]
SHIP_RATE_ESTIMATED_SPREAD = 0.20   # much wider: +-20 %
# Cargo waiting costs money (capital tied up). Sea-Intelligence benchmark: $40,000 of cargo per TEU,
# at a 5 % or 10 % annual rate. Per TEU per day: 40,000 x rate / 365.
CARGO_VALUE_PER_TEU_USD = 40000
CARGO_CAPITAL_RATE = (0.05, 0.10)
