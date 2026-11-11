"""
collector.py - Listens to live ship signals (AIS) and saves ships heading to Hamburg.

How to run it (in the VS Code terminal):
    python collector.py              -> listens for 15 minutes, then saves
    python collector.py --minutes 30 -> listens for 30 minutes

You need a free API key from https://aisstream.io, saved in a file called .env:
    AISSTREAM_API_KEY=your_key_here

What AIS is: every large ship broadcasts its position, speed, destination and ETA
by radio. AISStream.io collects these signals from land-based receivers and
sends them to us over the internet.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import websockets
from dotenv import load_dotenv

import config
from risk import is_bound_for_hamburg, sea_area
from safety import clean_ais_text, to_float, to_int


# ---------------------------------------------------------------------------
# Saving and loading
# ---------------------------------------------------------------------------
def load_store() -> dict:
    """Load ships saved by earlier runs, so data builds up over time."""
    if config.LIVE_DATA_FILE.exists():
        with open(config.LIVE_DATA_FILE, encoding="utf-8") as f:
            return json.load(f).get("ships", {})
    return {}


def save_store(ships: dict) -> int:
    """
    Save only ships heading to Hamburg (keeps the file small)
    and forget ships we have not heard from for a long time.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=config.FORGET_AFTER_HOURS)
    keep = {}
    for mmsi, ship in ships.items():
        if not is_bound_for_hamburg(ship.get("destination")) or ship.get("lat") is None:
            continue
        last = ship.get("last_position_utc")
        if last and datetime.fromisoformat(last) < cutoff:
            continue
        keep[mmsi] = ship

    config.DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "meta": {"updated_utc": now.isoformat(timespec="seconds"), "source": "AISStream.io (live AIS)"},
        "ships": keep,
    }
    temp = config.LIVE_DATA_FILE.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    temp.replace(config.LIVE_DATA_FILE)   # replace in one step, so a crash never leaves half a file
    return len(keep)


# ---------------------------------------------------------------------------
# Reading one AIS message
# ---------------------------------------------------------------------------
def _meta_value(meta: dict, *names):
    """AISStream sometimes uses 'latitude', sometimes 'Latitude'. Accept both."""
    for name in names:
        if name in meta and meta[name] not in (None, ""):
            return meta[name]
    return None


def _clean_eta(eta) -> dict | None:
    """Keep only the four ETA numbers, as whole numbers. Anything else is dropped."""
    if not isinstance(eta, dict):
        return None
    return {key: to_int(eta.get(key), 0, 60) or 0 for key in ("Month", "Day", "Hour", "Minute")}


def handle_message(ships: dict, msg: dict) -> None:
    """
    Update our list of ships with one incoming message.
    Everything in the message is untrusted (see safety.py), so every value is
    checked and cleaned before we keep it.
    """
    if not isinstance(msg, dict):
        return
    kind = msg.get("MessageType")
    meta = msg.get("MetaData") if isinstance(msg.get("MetaData"), dict) else {}
    message = msg.get("Message") if isinstance(msg.get("Message"), dict) else {}
    body = message.get(kind) if isinstance(message.get(kind), dict) else {}

    # MMSI = the ship's 9-digit radio ID. We use it as the key, so it must be a real number.
    mmsi = to_int(_meta_value(meta, "MMSI") or body.get("UserID"), 1, 999_999_999)
    if mmsi is None:
        return
    mmsi = str(mmsi)
    ship = ships.setdefault(mmsi, {"mmsi": mmsi})

    name = clean_ais_text(_meta_value(meta, "ShipName", "shipname"), "name")
    if name:
        ship["name"] = name

    if kind == "PositionReport":
        lat = to_float(body.get("Latitude"), -90, 90)      # 91/181 means "position not available"
        lon = to_float(body.get("Longitude"), -180, 180)
        if lat is None or lon is None:
            return
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ship.update({
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "sog": to_float(body.get("Sog"), 0, 102.3),     # speed over ground, knots
            "cog": to_float(body.get("Cog"), 0, 360),       # course over ground, degrees
            "nav_status": to_int(body.get("NavigationalStatus"), 0, 15),
            "last_position_utc": now,
        })
        if "first_seen_utc" not in ship:
            ship.update({"first_seen_utc": now, "first_seen_lat": lat, "first_seen_lon": lon})
        # Remember the areas the ship passed through, to guess its route later.
        area = sea_area(lat, lon)
        if area == "Mediterranean":
            ship["seen_in_mediterranean"] = True
        elif area == "Off West Africa":
            ship["seen_off_west_africa"] = True

    elif kind == "ShipStaticData":
        ship.update({
            "destination": clean_ais_text(body.get("Destination"), "destination"),
            "eta": _clean_eta(body.get("Eta")),                  # {"Month":..,"Day":..,"Hour":..,"Minute":..}
            "ship_type": to_int(body.get("Type"), 0, 99),        # 70-79 = cargo ships (incl. container ships)
            "imo": to_int(body.get("ImoNumber"), 1, 9_999_999),  # 7-digit ship ID
            "callsign": clean_ais_text(body.get("CallSign"), "callsign"),
            "draught_m": to_float(body.get("MaximumStaticDraught"), 0, 25.5),
            "name": clean_ais_text(body.get("Name"), "name") or ship.get("name", ""),
            "last_static_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })


# ---------------------------------------------------------------------------
# Listening loop
# ---------------------------------------------------------------------------
async def listen(api_key: str, minutes: float) -> None:
    ships = load_store()
    print(f"Loaded {len(ships)} Hamburg-bound ships from earlier runs.")
    end_time = time.monotonic() + minutes * 60
    last_save = time.monotonic()
    received = 0

    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": config.BOUNDING_BOXES,
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }

    while time.monotonic() < end_time:
        try:
            async with websockets.connect(config.AISSTREAM_URL, max_size=2**22) as ws:
                await ws.send(json.dumps(subscription))   # must be sent within 3 seconds
                print("Connected. Listening for ships... (press Ctrl+C to stop early)")
                while time.monotonic() < end_time:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        msg = json.loads(raw)
                    except (TypeError, ValueError):
                        continue                              # not valid JSON: ignore it
                    if not isinstance(msg, dict):
                        continue
                    if "error" in msg:
                        sys.exit(f"AISStream refused the connection: {str(msg['error'])[:200]!r}\n"
                                 "Check that your API key in .env is correct.")
                    handle_message(ships, msg)
                    received += 1

                    if time.monotonic() - last_save > 60:   # save every minute
                        saved = save_store(ships)
                        left = (end_time - time.monotonic()) / 60
                        print(f"  {received:,} messages | {len(ships):,} ships seen | "
                              f"{saved} heading to Hamburg | {left:.0f} min left")
                        last_save = time.monotonic()
        except (websockets.ConnectionClosed, OSError) as error:
            print(f"Connection lost ({error}). Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

    saved = save_store(ships)
    print(f"\nDone. {received:,} messages received. {saved} Hamburg-bound ships saved to {config.LIVE_DATA_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect live AIS data for ships heading to Hamburg.")
    parser.add_argument("--minutes", type=float, default=config.DEFAULT_RUN_MINUTES,
                        help=f"How long to listen (default {config.DEFAULT_RUN_MINUTES})")
    args = parser.parse_args()

    load_dotenv(config.PROJECT_DIR / ".env")
    api_key = os.getenv("AISSTREAM_API_KEY", "").strip()
    if not api_key or api_key == "paste_your_key_here":
        sys.exit("No API key found.\n"
                 "1. Get a free key at https://aisstream.io\n"
                 "2. Open the file .env in this folder\n"
                 "3. Put your key after AISSTREAM_API_KEY=  and save the file.")

    try:
        asyncio.run(listen(api_key, args.minutes))
    except KeyboardInterrupt:
        print("\nStopped early. Data saved up to the last minute is kept.")


if __name__ == "__main__":
    main()
