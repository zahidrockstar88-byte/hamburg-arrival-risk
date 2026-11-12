"""
Checks for voyage.py: fuel, CO2 and EU ETS cost; Suez vs Cape; and slower sailing.
Expected values are worked out by hand from the sourced figures in config.py.
Run with:  python -m pytest
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from voyage import compare_routes, slower_by, voyage_emissions  # noqa: E402


def test_one_day_at_sea_worked_example():
    # 13,000 TEU at 18 kn covers 432 nm in exactly 1 day: 109-147 t fuel (sourced reference, +35 % high end).
    # CO2 = fuel x 3.151 = 343.5-463.2 t. EU ETS into the EU (50 %): x 0.5 x EUR 60-90 x 1.10 = $11,334-22,928.
    # Fuel cost: 109 x $670 = $73,030 to 147 x $730 = $107,310.
    trip = voyage_emissions(13000, speed_kn=18, distance_nm=432, eu_share=0.5)
    assert trip["days"] == 1.0
    assert trip["fuel_t"] == (109, 147)
    assert round(trip["co2_t"][0], 1) == 343.5 and round(trip["co2_t"][1], 1) == 463.2
    assert round(trip["ets_usd"][0]) == 11334 and round(trip["ets_usd"][1]) == 22928
    assert trip["fuel_usd"] == (73030, 107310)


def test_half_the_speed_burns_a_quarter_of_the_fuel_for_the_same_distance():
    # Fuel per day goes with the cube of speed; half speed takes twice as long: 1/8 x 2 = 1/4.
    fast = voyage_emissions(13000, speed_kn=18, distance_nm=432, eu_share=0.5)
    slow = voyage_emissions(13000, speed_kn=9, distance_nm=432, eu_share=0.5)
    assert abs(slow["fuel_t"][0] - fast["fuel_t"][0] / 4) < 1e-9
    assert slow["days"] == 2.0


def test_between_eu_ports_the_full_emissions_count():
    into_eu = voyage_emissions(13000, speed_kn=18, distance_nm=432, eu_share=0.5)
    within_eu = voyage_emissions(13000, speed_kn=18, distance_nm=432, eu_share=1.0)
    assert abs(within_eu["ets_usd"][1] - 2 * into_eu["ets_usd"][1]) < 1e-6



def test_suez_or_cape_worked_example():
    # 13,000 TEU at 18 kn = 432 nm a day. Suez 10,800 nm = 25.0 days, Cape 14,040 nm = 32.5 days: 7.5 days more.
    # A weekly service loses 2 x 7.5 = 15 days per round trip -> 15 / 7 = 2.1 -> 3 extra ships.
    # Suez toll: 13,000 TEU x $55-80 = $715,000-1,040,000; nothing around the Cape.
    result = compare_routes(13000, speed_kn=18, suez_nm=10800, cape_nm=14040)
    suez, cape = result["Suez Canal"], result["Cape of Good Hope"]
    assert suez["days"] == 25.0 and cape["days"] == 32.5
    assert result["extra_days"] == 7.5 and result["extra_nm"] == 3240
    assert result["extra_ships_weekly"] == 3
    assert suez["toll_usd"] == (715000, 1040000) and cape["toll_usd"] == (0, 0)
    assert cape["fuel_t"][0] / suez["fuel_t"][0] == 32.5 / 25.0          # same speed: fuel grows with distance
    assert cape["co2_t"][0] > suez["co2_t"][0]


def test_a_route_total_adds_up_its_parts():
    route = compare_routes(13000, speed_kn=18, suez_nm=10800, cape_nm=14040)["Suez Canal"]
    for end in (0, 1):
        parts = route["fuel_usd"][end] + route["ets_usd"][end] + route["charter_usd"][end] + route["toll_usd"][end]
        assert abs(route["total_usd"][end] - parts) < 1e-6



def test_sailing_two_knots_slower_worked_example():
    # 1,000 nm at 18 kn = 55.6 h; at 16 kn = 62.5 h: 6.9 h later.
    # Fuel per mile goes with the square of speed: 1 - (16/18)^2 = 21.0 % less fuel and CO2.
    change = slower_by(13000, speed_kn=18, distance_nm=1000, knots_slower=2, eu_share=0.5)
    assert round(change["hours_later"], 1) == 6.9
    assert round(change["share_saved"], 3) == 0.210
    assert change["co2_saved_t"][0] > 0 and change["money_saved_usd"][0] > 0


def test_cannot_slow_down_more_than_the_ship_is_going():
    assert slower_by(13000, speed_kn=10, distance_nm=1000, knots_slower=10, eu_share=0.5) is None
