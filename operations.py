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
from typing import NamedTuple

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


def estimate_teu(length_m: float | None) -> tuple[int | None, str]:
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
def hamburg_teu(teu: int) -> tuple[float, float]:
    """How many TEU of this ship are unloaded in Hamburg: (fewest, most), from the share in config.py."""
    share_low, share_high = config.UNLOAD_SHARE_RANGE
    return teu * share_low, teu * share_high


class Unloading(NamedTuple):
    fastest_h: float     # few containers, quick cranes
    slowest_h: float     # many containers, slow cranes
    cranes: float        # average number of cranes working the ship
    moves_low: int       # crane moves for the Hamburg containers (fewest, most)
    moves_high: int


def unloading(teu: int) -> Unloading:
    """How long unloading the Hamburg containers takes, with the cranes and moves behind it."""
    teu_low, teu_high = hamburg_teu(teu)
    moves_low, moves_high = teu_low / config.TEU_PER_MOVE, teu_high / config.TEU_PER_MOVE
    cranes = _interpolate(config.CRANE_INTENSITY_BY_TEU, teu)   # average cranes (can be 3.4: they join and leave)
    slow_crane, fast_crane = config.CRANE_MOVES_PER_HOUR          # moves per crane per hour
    slow_ceiling, fast_ceiling = (moves / 24 for moves in config.MAX_MOVES_PER_SHIP_PER_DAY)
    slow_rate = min(cranes * slow_crane, slow_ceiling)            # moves per hour for the whole ship
    fast_rate = min(cranes * fast_crane, fast_ceiling)
    return Unloading(moves_low / fast_rate, moves_high / slow_rate, cranes, round(moves_low), round(moves_high))


def after_berth(berth_time: datetime, teu: int, warehouse_km: float) -> dict:
    """
    Timeline after berthing, each step as (earliest, latest):
      unloading_starts, first_ready (first boxes available for pickup), all_ready,
      on_a_train (by rail), at_warehouse_first, at_warehouse_all (by truck).
    """
    unload = unloading(teu)
    fast_h, slow_h = unload.fastest_h, unload.slowest_h
    start_lo, start_hi = config.START_UNLOADING_AFTER_BERTH_H
    ready_lo, ready_hi = config.READY_FOR_PICKUP_AFTER_UNLOAD_H
    speed_lo, speed_hi = config.TRUCK_SPEED_KMH
    gate_lo, gate_hi = config.TERMINAL_GATE_H
    drive_lo = gate_lo + warehouse_km / speed_hi        # quick gate, free-flowing roads
    drive_hi = gate_hi + warehouse_km / speed_lo        # slow gate, port traffic

    def hours_after_berth(hours: float) -> datetime:
        return berth_time + timedelta(hours=hours)

    at = hours_after_berth           # short name, so each step below fits on one readable line

    return {
        "cranes": unload.cranes,
        "moves": (unload.moves_low, unload.moves_high),
        "unloading_hours": (fast_h, slow_h),
        "unloading_starts": (at(start_lo), at(start_hi)),
        "first_ready": (at(start_lo + ready_lo), at(start_hi + ready_hi)),
        "all_ready": (at(start_lo + fast_h + ready_lo), at(start_hi + slow_h + ready_hi)),
        "on_a_train": (at(start_lo + ready_lo + config.RAIL_WAIT_FOR_TRAIN_H[0]),
                       at(start_hi + slow_h + ready_hi + config.RAIL_WAIT_FOR_TRAIN_H[1])),
        "at_warehouse_first": (at(start_lo + ready_lo + drive_lo), at(start_hi + ready_hi + drive_hi)),
        "at_warehouse_all": (at(start_lo + fast_h + ready_lo + drive_lo),
                             at(start_hi + slow_h + ready_hi + drive_hi)),
    }


# ---------------------------------------------------------------------------
# 3. Cost of delay
# ---------------------------------------------------------------------------
SOURCED_RATE = "New ConTex charter index"
ESTIMATED_RATE = "estimate (bigger than the sourced index classes)"


def ship_cost_per_day(teu: int) -> tuple[float, float, str]:
    """
    Daily cost of the ship's time: (low, high, basis). Read off a smooth line through the charter-rate
    points in config.py; ships up to 4,250 TEU use the sourced New ConTex points, bigger ones our estimate.
    """
    sourced_up_to = config.SHIP_RATE_SOURCED[-1][0]
    rate = _interpolate(config.SHIP_RATE_SOURCED + config.SHIP_RATE_ESTIMATED, teu)
    spread = _interpolate(config.SHIP_RATE_SPREAD_BY_TEU, teu)      # grows smoothly away from the sourced data
    basis = SOURCED_RATE if teu <= sourced_up_to else ESTIMATED_RATE
    return rate * (1 - spread), rate * (1 + spread), basis


def delay_cost(teu: int, hours_late: float) -> dict | None:
    """
    What a delay costs, in US dollars, as (low, high) ranges:
      ship  - the ship's time: charter rate per day x days late
      cargo - capital tied up in the Hamburg containers: value x yearly rate / 365 x days late
    Fuel and demurrage are left out on purpose: a ship waiting at anchor burns little fuel, and
    demurrage only starts after unloading, so a late ship doesn't cause it.
    Returns None when the ship is not late.
    """
    if hours_late is None or hours_late <= 0:
        return None
    days = hours_late / 24
    day_low, day_high, basis = ship_cost_per_day(teu)
    teu_low, teu_high = hamburg_teu(teu)
    rate_low, rate_high = config.CARGO_CAPITAL_RATE
    cargo_low = teu_low * config.CARGO_VALUE_PER_TEU_USD * rate_low / 365 * days
    cargo_high = teu_high * config.CARGO_VALUE_PER_TEU_USD * rate_high / 365 * days
    ship_low, ship_high = day_low * days, day_high * days
    return {
        "days": days,
        "ship": (ship_low, ship_high),
        "cargo": (cargo_low, cargo_high),
        "total": (ship_low + cargo_low, ship_high + cargo_high),
        "rate_basis": basis,
    }


def total_cost(costs: list[dict]) -> tuple[float, float]:
    """Add up several delay costs: (lowest total, highest total)."""
    return sum(cost["total"][0] for cost in costs), sum(cost["total"][1] for cost in costs)


def money_range(low: float, high: float) -> str:
    """'$12k–$18k' style range, rounded to what the estimate can honestly support."""
    def short(value: float) -> str:
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if value >= 1000:
            return f"${value / 1000:.0f}k"
        return f"${value:.0f}"
    return f"{short(low)}–{short(high)}"
