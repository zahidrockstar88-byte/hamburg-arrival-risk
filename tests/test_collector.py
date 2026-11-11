"""
Checks for collector.py: values from the ship's radio signal are cleaned before they are saved.
Run with:  python -m pytest
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collector import handle_message  # noqa: E402


def test_ship_length_from_the_radio_signal_is_checked():
    def length_from(dimension):
        ships = {}
        handle_message(ships, {"MessageType": "ShipStaticData", "MetaData": {"MMSI": 211000009},
                               "Message": {"ShipStaticData": {"Name": "TEST", "Dimension": dimension}}})
        return ships["211000009"]["length_m"]
    assert length_from({"A": 300, "B": 66, "C": 20, "D": 31}) == 366        # bow + stern
    assert length_from({"A": 0, "B": 0}) is None                             # "not available"
    assert length_from({"A": 511, "B": 511}) is None                         # impossible: over 460 m
    assert length_from({"A": "x", "B": 10}) is None and length_from("broken") is None
