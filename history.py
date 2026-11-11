"""
history.py - What really happened: ships we saw at sea and later saw moored in Hamburg.

Where the history comes from: the GitHub Action saves data/ships.json every ~3 hours and git
keeps every saved version. Each version is a "snapshot". Reading them in order shows when each
ship was out at sea and when it was first moored in Hamburg (its arrival, see GLOSSARY.md).

Being honest about time: we only look every ~3 hours, so we never know the exact berthing time.
We know a WINDOW: after the last time we saw the ship still under way, and no later than the
first time we saw it moored. A judgement like "late" is only made when the whole window agrees.

Used for:
  - the carrier reliability scorecard (procurement: which shipping line keeps its promises?)
  - the experimental ML ETA (eta_model.py)

Run it inside the project folder (it reads the git history):
    python history.py
It writes data/arrivals.json, which app.py reads.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import config
from risk import ARRIVAL_FLAGS, assess_ship, parse_ais_eta, parse_time, shipping_line
from safety import clean_ais_text, clean_saved_ship, to_float

ARRIVALS_FILE = config.DATA_DIR / "arrivals.json"
OTHER_LINE = "Line unknown"          # ships whose name doesn't reveal the shipping line


# ---------------------------------------------------------------------------
# 1. Snapshots and sightings
# ---------------------------------------------------------------------------
def load_snapshots_from_git(repo: Path = config.PROJECT_DIR) -> list[dict]:
    """Return every saved version of data/ships.json, oldest first."""
    def git(*args) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout

    snapshots = []
    for sha in reversed(git("log", "--format=%H", "--", "data/ships.json").split()):
        try:
            snapshots.append(json.loads(git("show", f"{sha}:data/ships.json")))
        except (subprocess.CalledProcessError, ValueError):
            continue                       # a broken or missing version: skip it
    return snapshots


def collect_sightings(snapshots: list[dict]) -> dict:
    """
    Every time we saw each ship: {mmsi: {position time: (dashboard row, cleaned ship)}}.
    The row is judged as of that moment, so its flag says what the ship was doing then.
    """
    sightings = {}
    for snapshot in snapshots:
        for raw in (snapshot.get("ships") or {}).values():
            ship = clean_saved_ship(raw)
            seen = parse_time((ship or {}).get("last_position_utc"))
            if not ship or not seen or not ship["mmsi"]:
                continue
            sightings.setdefault(ship["mmsi"], {})[seen] = (assess_ship(ship, now=seen), ship)
    return sightings


# ---------------------------------------------------------------------------
# 2. Arrivals
# ---------------------------------------------------------------------------
def build_arrivals(snapshots: list[dict]) -> list[dict]:
    """
    One record per ship that we saw under way (not arriving, not arrived) and later saw moored in Hamburg.
      promised_eta  - the ETA the crew reported the FIRST time we saw the ship (its promise)
      arrived_after / arrived_by - the window in which it berthed
    """
    arrivals = []
    for mmsi, by_time in collect_sightings(snapshots).items():
        times = sorted(by_time)
        arrived_by = next((t for t in times if by_time[t][0]["Flag"] == "🔵"), None)
        if arrived_by is None:
            continue
        under_way = [t for t in times if t < arrived_by and by_time[t][0]["Flag"] not in ARRIVAL_FLAGS]
        if not under_way:
            continue                       # first seen already in port: no promise to check
        earlier = [t for t in times if t < arrived_by]
        first_seen = under_way[0]
        first_ship = by_time[first_seen][1]
        moored_ship = by_time[arrived_by][1]
        line = shipping_line(moored_ship.get("name") or first_ship.get("name"))
        promised = parse_ais_eta(first_ship.get("eta"), first_seen)
        arrivals.append({
            "mmsi": mmsi,
            "ship": moored_ship.get("name") or first_ship.get("name") or f"MMSI {mmsi}",
            "line": line[0] if line else OTHER_LINE,
            "first_seen": first_seen.isoformat(),
            "promised_eta": promised.isoformat() if promised else None,
            "arrived_after": max(earlier).isoformat(),
            "arrived_by": arrived_by.isoformat(),
        })
    return sorted(arrivals, key=lambda a: a["arrived_by"])


def judge(arrival: dict, tolerance_h: float = config.ON_TIME_TOLERANCE_HOURS) -> str:
    """
    On time, Late, Early, Unclear (the berthing window straddles the limit) or No ETA.
    Late  = it can't have berthed before promised + tolerance.
    Early = it berthed before promised - tolerance for sure.
    """
    promised = parse_time(arrival.get("promised_eta"))
    after, by = parse_time(arrival.get("arrived_after")), parse_time(arrival.get("arrived_by"))
    if promised is None or after is None or by is None:
        return "No ETA"
    hours_after = (after - promised).total_seconds() / 3600      # earliest possible lateness
    hours_by = (by - promised).total_seconds() / 3600            # latest possible lateness
    if hours_after > tolerance_h:
        return "Late"
    if hours_by < -tolerance_h:
        return "Early"
    if -tolerance_h <= hours_after and hours_by <= tolerance_h:
        return "On time"
    return "Unclear"


def delay_hours(arrival: dict) -> float | None:
    """Best estimate of how late (+) or early (-) the ship berthed: the middle of the window."""
    promised = parse_time(arrival.get("promised_eta"))
    after, by = parse_time(arrival.get("arrived_after")), parse_time(arrival.get("arrived_by"))
    if promised is None or after is None or by is None:
        return None
    middle = after + (by - after) / 2
    return (middle - promised).total_seconds() / 3600


# ---------------------------------------------------------------------------
# 3. Carrier scorecard
# ---------------------------------------------------------------------------
def scorecard(arrivals: list[dict]) -> list[dict]:
    """
    One row per shipping line, plus "All ships" first. Schedule reliability = on time / judged arrivals,
    shown only when there are at least MIN_ARRIVALS_FOR_SCORE judged arrivals.
    """
    groups = {"All ships": arrivals}
    for arrival in arrivals:
        groups.setdefault(arrival["line"], []).append(arrival)
    rows = []
    for line, group in groups.items():
        verdicts = [judge(a) for a in group]
        judged = sum(v in ("On time", "Late", "Early") for v in verdicts)
        delays = [d for d in (delay_hours(a) for a in group) if d is not None]
        on_time = verdicts.count("On time")
        rows.append({
            "Shipping line": line,
            "Arrivals": len(group),
            "On time": on_time,
            "Late": verdicts.count("Late"),
            "Early": verdicts.count("Early"),
            "Unclear": verdicts.count("Unclear") + verdicts.count("No ETA"),
            "Reliability": (on_time / judged) if judged >= config.MIN_ARRIVALS_FOR_SCORE else None,
            "Average delay (h)": round(sum(delays) / len(delays), 1) if delays else None,
        })
    first, rest = rows[0], sorted(rows[1:], key=lambda r: (r["Shipping line"] == OTHER_LINE, -r["Arrivals"]))
    return [first, *rest]


# ---------------------------------------------------------------------------
# 4. Saving and loading
# ---------------------------------------------------------------------------
def load_arrivals(path: Path = ARRIVALS_FILE) -> tuple[list[dict], datetime | None]:
    """
    Read data/arrivals.json. A bot writes it, so every field is checked again here;
    a broken record is skipped, never shown.
    """
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return [], None
    records = saved.get("arrivals") if isinstance(saved, dict) else None
    clean = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        times = {key: parse_time(record.get(key)) if isinstance(record.get(key), str) else None
                 for key in ("first_seen", "promised_eta", "arrived_after", "arrived_by")}
        if not (times["arrived_after"] and times["arrived_by"] and times["arrived_after"] <= times["arrived_by"]):
            continue
        line = record.get("line") if isinstance(record.get("line"), str) else OTHER_LINE
        clean.append({
            "mmsi": str(record.get("mmsi", ""))[:9],
            "ship": clean_ais_text(record.get("ship"), "name") or "Unknown ship",
            "line": line[:40],
            **{key: (value.isoformat() if value else None) for key, value in times.items()},
        })
    updated = parse_time(saved.get("updated_utc")) if isinstance(saved, dict) and isinstance(
        saved.get("updated_utc"), str) else None
    return clean, updated


def main() -> None:
    arrivals = build_arrivals(load_snapshots_from_git())
    config.DATA_DIR.mkdir(exist_ok=True)
    payload = {"updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "arrivals": arrivals}
    with open(ARRIVALS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    print(f"Arrivals rebuilt from git history: {len(arrivals)}")
    for row in scorecard(arrivals):
        score = f"{row['Reliability']:.0%}" if row["Reliability"] is not None else "not enough data"
        print(f"  {row['Shipping line']}: {row['Arrivals']} arrival(s), reliability {score}")


if __name__ == "__main__":
    main()
