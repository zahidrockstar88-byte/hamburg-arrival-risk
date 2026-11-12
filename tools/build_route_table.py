"""
tools/build_route_table.py - Builds data/asia_routes.json: sea distances from Asian ports to Hamburg,
via the Suez Canal and around the Cape of Good Hope.

Run once (it is not needed by the dashboard, which only reads the finished table):
    pip install searoute==1.6.0
    python tools/build_route_table.py

How it works:
  - searoute (Apache-2.0, based on Eurostat's SeaRoute shipping-lane network) finds the shortest sea route.
    Blocking the Suez Canal forces the route around Africa.
  - Check against published figures: Shanghai -> Rotterdam is 10,513-10,600 nm via Suez and 13,793-13,800 nm
    via the Cape (Port Economics, Management and Policy; Carra Globe). searoute gives 10,514 and 13,479:
    Suez is spot on, the Cape is ~2.3 % short (the network hugs the coast; real ships stay further out).
    So every distance is multiplied by the factor that makes Shanghai -> Rotterdam match the published middle.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import searoute as sr

HAMBURG = [9.97, 53.54]
ROTTERDAM = [4.05, 51.98]
SHANGHAI = [122.0, 30.6]
PUBLISHED_SHANGHAI_ROTTERDAM_NM = {"suez": 10555, "cape": 13797}   # middles of the published ranges

# Main Asian container ports with services to Hamburg: name -> (region, [lon, lat] of the port approach).
PORTS = {
    "Shanghai": ("East Asia", [122.0, 30.6]),
    "Ningbo": ("East Asia", [122.1, 29.9]),
    "Qingdao": ("East Asia", [120.4, 36.0]),
    "Tianjin": ("East Asia", [117.9, 38.9]),
    "Xiamen": ("East Asia", [118.1, 24.45]),
    "Shenzhen (Yantian)": ("East Asia", [114.3, 22.55]),
    "Hong Kong": ("East Asia", [114.15, 22.3]),
    "Kaohsiung": ("East Asia", [120.3, 22.6]),
    "Busan": ("East Asia", [129.05, 35.1]),
    "Tokyo / Yokohama": ("East Asia", [139.7, 35.4]),
    "Singapore": ("Southeast Asia", [103.85, 1.26]),
    "Tanjung Pelepas": ("Southeast Asia", [103.55, 1.36]),
    "Port Klang": ("Southeast Asia", [101.35, 3.0]),
    "Laem Chabang": ("Southeast Asia", [100.9, 13.08]),
    "Cai Mep (Ho Chi Minh City)": ("Southeast Asia", [107.05, 10.5]),
    "Jakarta (Tanjung Priok)": ("Southeast Asia", [106.88, -6.1]),
    "Manila": ("Southeast Asia", [120.95, 14.6]),
    "Nhava Sheva (Mumbai)": ("South Asia", [72.95, 18.95]),
    "Mundra": ("South Asia", [69.7, 22.75]),
    "Colombo": ("South Asia", [79.85, 6.95]),
    "Chennai": ("South Asia", [80.3, 13.1]),
    "Chittagong": ("South Asia", [91.8, 22.3]),
    "Karachi": ("South Asia", [66.98, 24.8]),
    "Jebel Ali (Dubai)": ("Middle East Gulf", [55.03, 25.0]),
    "Dammam": ("Middle East Gulf", [50.2, 26.5]),
}


def distance_nm(origin, destination, block_suez):
    restrictions = ["northwest"] + (["suez"] if block_suez else [])
    route = sr.searoute(origin, destination, units="naut", restrictions=restrictions)
    return route.properties["length"]


def main():
    factor = {
        "suez": PUBLISHED_SHANGHAI_ROTTERDAM_NM["suez"] / distance_nm(SHANGHAI, ROTTERDAM, block_suez=False),
        "cape": PUBLISHED_SHANGHAI_ROTTERDAM_NM["cape"] / distance_nm(SHANGHAI, ROTTERDAM, block_suez=True),
    }
    routes = {}
    for port, (region, where) in PORTS.items():
        routes[port] = {
            "region": region,
            "suez_nm": round(distance_nm(where, HAMBURG, block_suez=False) * factor["suez"]),
            "cape_nm": round(distance_nm(where, HAMBURG, block_suez=True) * factor["cape"]),
        }
        print(f"{port:28} {routes[port]['suez_nm']:6,} nm via Suez  {routes[port]['cape_nm']:6,} nm via the Cape")
    payload = {
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "searoute 1.6.0 (Eurostat SeaRoute network), calibrated to published Shanghai-Rotterdam distances",
        "calibration": {k: round(v, 4) for k, v in factor.items()},
        "routes": routes,
    }
    out = Path(__file__).resolve().parent.parent / "data" / "asia_routes.json"
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(routes)} ports to {out} (calibration: {payload['calibration']})")


if __name__ == "__main__":
    main()
