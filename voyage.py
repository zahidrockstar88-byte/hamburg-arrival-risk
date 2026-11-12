"""
voyage.py - What a voyage burns, emits and costs, and the choice between the Suez Canal and the Cape.

Three questions, answered with RANGES (low, high):
  1. Fuel, CO2 and EU ETS cost of a trip: how much fuel a ship burns depends on its size and,
     much more, on its speed (fuel per day grows with the CUBE of speed).
  2. Suez or the Cape: for a Shanghai -> Hamburg voyage, what does the detour around Africa add
     in distance, days, fuel, CO2 and money, and how many extra ships a weekly service needs?
  3. Slower sailing ("slow steaming"): what does a few knots slower save, and how much later does
     the ship arrive?

Every figure comes from config.py, with its source or marked there as an assumption.
"""

from __future__ import annotations

import math

import config
from operations import ship_cost_per_day


# ---------------------------------------------------------------------------
# 1. Fuel, CO2 and EU ETS cost
# ---------------------------------------------------------------------------
def voyage_emissions(teu: float, speed_kn: float, distance_nm: float, eu_share: float) -> dict:
    """
    Fuel, CO2 and costs of sailing `distance_nm` at `speed_kn`, each as (low, high).
    eu_share: the part of the emissions the EU ETS counts (0.5 into or out of the EU, 1.0 between EU ports).
    """
    reference = config.FUEL_REFERENCE
    size_factor = (teu / reference["teu"]) ** (2 / 3)             # bigger ships burn more, but not in proportion
    speed_factor = (speed_kn / reference["speed_kn"]) ** 3         # double the speed = 8 times the fuel per day
    days = distance_nm / (speed_kn * 24)
    fuel_low, fuel_high = (per_day * size_factor * speed_factor * days for per_day in reference["tonnes_per_day"])
    co2_low, co2_high = fuel_low * config.CO2_PER_TONNE_FUEL, fuel_high * config.CO2_PER_TONNE_FUEL
    ets_low_eur, ets_high_eur = config.ETS_PRICE_PER_TONNE_EUR
    price_low, price_high = config.FUEL_PRICE_PER_TONNE_USD
    return {
        "days": days,
        "fuel_t": (fuel_low, fuel_high),
        "co2_t": (co2_low, co2_high),
        "ets_usd": (co2_low * eu_share * ets_low_eur * config.EUR_TO_USD,
                    co2_high * eu_share * ets_high_eur * config.EUR_TO_USD),
        "fuel_usd": (fuel_low * price_low, fuel_high * price_high),
    }


# ---------------------------------------------------------------------------
# 2. Suez Canal or Cape of Good Hope
# ---------------------------------------------------------------------------
def compare_routes(teu: float, speed_kn: float, suez_nm: float, cape_nm: float) -> dict:
    """
    The same voyage to Hamburg by both routes, at the same speed. For each route (low, high) ranges of:
    fuel, CO2, EU ETS (50 %: the voyage comes from outside the EU), fuel cost, charter cost (the ship's time),
    Suez toll and the total. Plus what the Cape adds, and how many extra ships a WEEKLY service needs to keep
    one departure a week when every round trip takes longer.
    """
    day_rate_low, day_rate_high, _basis = ship_cost_per_day(teu)
    toll_low, toll_high = config.SUEZ_TOLL_PER_TEU_USD
    result = {}
    for route, distance, toll in (("Suez Canal", suez_nm, (teu * toll_low, teu * toll_high)),
                                  ("Cape of Good Hope", cape_nm, (0, 0))):
        trip = voyage_emissions(teu, speed_kn, distance, config.ETS_SHARE_FROM_OUTSIDE_EU)
        charter = (trip["days"] * day_rate_low, trip["days"] * day_rate_high)
        total = tuple(trip["fuel_usd"][end] + trip["ets_usd"][end] + charter[end] + toll[end] for end in (0, 1))
        result[route] = {**trip, "distance_nm": distance, "charter_usd": charter, "toll_usd": toll, "total_usd": total}
    extra_days = result["Cape of Good Hope"]["days"] - result["Suez Canal"]["days"]
    result["extra_nm"] = cape_nm - suez_nm
    result["extra_days"] = extra_days
    result["extra_ships_weekly"] = math.ceil(2 * extra_days / 7)     # round trip is 2 x longer; one ship per week of delay
    return result


# ---------------------------------------------------------------------------
# 3. Sailing slower ("slow steaming")
# ---------------------------------------------------------------------------
def slower_by(teu: float, speed_kn: float, distance_nm: float, knots_slower: float, eu_share: float) -> dict | None:
    """
    What sailing `knots_slower` slower for `distance_nm` changes: hours later, the share of fuel saved,
    and the fuel, CO2 and money (fuel + EU ETS) saved as (low, high). None if it would mean stopping.
    Fuel per DAY goes with the cube of speed, but the trip takes longer, so fuel per MILE goes with the square.
    """
    new_speed = speed_kn - knots_slower
    if new_speed <= 0:
        return None
    now = voyage_emissions(teu, speed_kn, distance_nm, eu_share)
    slower = voyage_emissions(teu, new_speed, distance_nm, eu_share)

    def saved(key: str) -> tuple[float, float]:
        return now[key][0] - slower[key][0], now[key][1] - slower[key][1]

    fuel_money, ets_money = saved("fuel_usd"), saved("ets_usd")
    return {
        "hours_later": (slower["days"] - now["days"]) * 24,
        "share_saved": 1 - (new_speed / speed_kn) ** 2,
        "fuel_saved_t": saved("fuel_t"),
        "co2_saved_t": saved("co2_t"),
        "money_saved_usd": (fuel_money[0] + ets_money[0], fuel_money[1] + ets_money[1]),
    }


# ---------------------------------------------------------------------------
# 4. The Asia -> Hamburg distance table (data/asia_routes.json, built by tools/build_route_table.py)
# ---------------------------------------------------------------------------
ROUTES_FILE = config.DATA_DIR / "asia_routes.json"


def load_asia_routes(path=ROUTES_FILE) -> dict:
    """{port: {"region", "suez_nm", "cape_nm"}}. Rows with missing or impossible distances are skipped."""
    import json
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return {}
    routes = saved.get("routes") if isinstance(saved, dict) else None
    clean = {}
    for port, row in (routes.items() if isinstance(routes, dict) else []):
        if not (isinstance(port, str) and isinstance(row, dict)):
            continue
        suez, cape = row.get("suez_nm"), row.get("cape_nm")
        if all(isinstance(d, (int, float)) and 1000 < d < 20000 for d in (suez, cape)) and cape > suez:
            clean[port[:40]] = {"region": str(row.get("region", ""))[:30], "suez_nm": suez, "cape_nm": cape}
    return clean
