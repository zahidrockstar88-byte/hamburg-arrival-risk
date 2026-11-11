"""
operations.py - What happens after a container ship berths, and what a delay costs.

Two questions, answered with RANGES (low, high), never one falsely precise number:
  1. After the berth: how long does unloading take, and when can a truck collect
     the containers and bring them to a warehouse?
  2. Cost of delay: what does it cost when a ship arrives later than it promised?
     (the ship's time, and the cargo's tied-up capital)

Every assumption lives in config.py with its source, or is marked there as a rule of thumb.
The numbers are estimates for planning and for discussion, not invoices.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import config


# ---------------------------------------------------------------------------
# 1. How big is the ship?
# ---------------------------------------------------------------------------
def _interpolate(points: list[tuple[float, float]], x: float) -> float:
    """Read a value off a table of (x, y) points, drawing straight lines between them."""
    if x <= points[0][0]:
        return points[0][1]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if x <= x2:
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return points[-1][1]


def estimate_teu(length_m: float | None, draught_m: float | None) -> tuple[int | None, str]:
    """
    Container capacity in TEU, and what it was based on. Only the ship's length is used: the draught a crew
    reports is the CURRENT one, and a part-loaded ship floats high, so a draught-based guess came out far too
    small (MAERSK SEOUL: 1,700 TEU). Without a length we say "size unknown" instead of guessing.
    """
    if length_m and length_m >= 60:
        return int(round(_interpolate(config.TEU_BY_LENGTH_M, length_m), -2)), f"length {length_m:.0f} m"
    return None, "size unknown"


# ---------------------------------------------------------------------------
# 2. After the berth
# ---------------------------------------------------------------------------
def cranes_for(teu: int) -> int:
    """Number of quay cranes that usually work a ship of this size."""
    return next(cranes for up_to, cranes in config.CRANES_BY_TEU if teu <= up_to)


def unloading_hours(teu: int) -> tuple[float, float, int, tuple[int, int]]:
    """
    How long unloading the Hamburg containers takes: (fastest hours, slowest hours, cranes, (moves low, high)).
    Fastest = few containers and quick cranes; slowest = many containers and slow cranes.
    """
    share_low, share_high = config.UNLOAD_SHARE_RANGE
    moves_low = teu * share_low / config.TEU_PER_MOVE
    moves_high = teu * share_high / config.TEU_PER_MOVE
    cranes = cranes_for(teu)
    rate_low, rate_high = (min(cranes * rate, config.MAX_MOVES_PER_SHIP_PER_HOUR)
                           for rate in config.CRANE_MOVES_PER_HOUR)
    return moves_low / rate_high, moves_high / rate_low, cranes, (round(moves_low), round(moves_high))


def after_berth(berth_time: datetime, teu: int, warehouse_km: float) -> dict:
    """
    Timeline after berthing, each step as (earliest, latest):
      unloading_starts, first_ready (first boxes released for pickup), all_unloaded,
      all_ready, at_warehouse_first, at_warehouse_all.
    """
    fast_h, slow_h, cranes, moves = unloading_hours(teu)
    start_lo, start_hi = config.START_UNLOADING_AFTER_BERTH_H
    ready_lo, ready_hi = config.READY_FOR_PICKUP_AFTER_UNLOAD_H
    speed_lo, speed_hi = config.TRUCK_SPEED_KMH
    gate_lo, gate_hi = config.TERMINAL_GATE_H
    drive_lo = gate_lo + warehouse_km / speed_hi        # quick gate, free-flowing roads
    drive_hi = gate_hi + warehouse_km / speed_lo        # slow gate, port traffic

    def at(hours: float) -> datetime:
        return berth_time + timedelta(hours=hours)

    return {
        "cranes": cranes,
        "moves": moves,
        "unloading_hours": (fast_h, slow_h),
        "unloading_starts": (at(start_lo), at(start_hi)),
        "first_ready": (at(start_lo + ready_lo), at(start_hi + ready_hi)),
        "all_unloaded": (at(start_lo + fast_h), at(start_hi + slow_h)),
        "all_ready": (at(start_lo + fast_h + ready_lo), at(start_hi + slow_h + ready_hi)),
        "at_warehouse_first": (at(start_lo + ready_lo + drive_lo), at(start_hi + ready_hi + drive_hi)),
        "at_warehouse_all": (at(start_lo + fast_h + ready_lo + drive_lo),
                             at(start_hi + slow_h + ready_hi + drive_hi)),
    }


# ---------------------------------------------------------------------------
# 3. Cost of delay
# ---------------------------------------------------------------------------
def ship_cost_per_day(teu: int) -> tuple[int, int, str]:
    """Daily cost of the ship's time (low, high, source) from the charter-rate table in config.py."""
    return next((low, high, source) for up_to, low, high, source in config.SHIP_COST_PER_DAY_USD if teu <= up_to)


def delay_cost(teu: int, delay_hours: float) -> dict | None:
    """
    What a delay costs, in US dollars, as (low, high) ranges:
      ship  - the ship's time: charter rate per day x days late
      cargo - capital tied up in the Hamburg containers: value x yearly rate / 365 x days late
    Fuel and demurrage are left out on purpose: a ship waiting at anchor burns little fuel, and
    demurrage only starts after unloading, so a late ship doesn't cause it.
    Returns None when the ship is not late.
    """
    if delay_hours is None or delay_hours <= 0:
        return None
    days = delay_hours / 24
    day_low, day_high, source = ship_cost_per_day(teu)
    share_low, share_high = config.UNLOAD_SHARE_RANGE
    rate_low, rate_high = config.CARGO_CAPITAL_RATE
    cargo_low = teu * share_low * config.CARGO_VALUE_PER_TEU_USD * rate_low / 365 * days
    cargo_high = teu * share_high * config.CARGO_VALUE_PER_TEU_USD * rate_high / 365 * days
    ship_low, ship_high = day_low * days, day_high * days
    return {
        "days": days,
        "ship": (ship_low, ship_high),
        "cargo": (cargo_low, cargo_high),
        "total": (ship_low + cargo_low, ship_high + cargo_high),
        "ship_rate_source": source,
    }


def money(low: float, high: float) -> str:
    """'$12k–$18k' style range, rounded to what the estimate can honestly support."""
    def short(value: float) -> str:
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if value >= 1000:
            return f"${value / 1000:.0f}k"
        return f"${value:.0f}"
    return f"{short(low)}–{short(high)}"
