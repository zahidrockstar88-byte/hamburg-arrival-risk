# 🚢 Hamburg Arrival Risk Monitor

A dashboard that watches container and cargo ships heading to the **Port of Hamburg** using live AIS data,
checks whether each ship's reported ETA is realistic, and flags ships at risk of arriving late.

> This is a **risk flag, not an ETA prediction.** It compares the ETA a crew reports with what distance and
> speed say is possible, and highlights the ones that don't fit.

## Why

Carrier schedule reliability fell to 29% in August 2026 (Xeneta). Importers, forwarders and terminals plan
trucks, staff and berths around ETAs that crews type by hand and often don't update. A quick, transparent
sanity check catches the unrealistic ones early.

## What it does

1. Listens to live AIS ship signals for the waters around Europe (via [AISStream.io](https://aisstream.io)).
2. Keeps ships whose destination means Hamburg (`HAMBURG`, `DEHAM`, `NLRTM>DEHAM`, ...).
3. Measures the distance left along the usual sea route (e.g. Gibraltar → Ushant → Dover Strait → Elbe).
4. Calculates an ETA from distance and speed, with slower speed on the River Elbe and a pilot/berth buffer.
5. Flags each ship: 🔴 likely late, 🟡 needs checking (old data, stopped, no ETA), 🟢 on track, ⚪ arriving.
6. Shows chokepoint risks on the way (Red Sea, Hormuz, North European congestion).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py          # opens with demo data, no key needed
```

For live data, add a free AISStream key to `.env` (see `.env.example`), then:

```bash
python collector.py --minutes 15
```

Full beginner steps: [SETUP_GUIDE.md](SETUP_GUIDE.md) · How the logic works: [HOW_IT_WORKS.md](HOW_IT_WORKS.md)

## Built with

Python · Streamlit · pydeck · AISStream.io websocket API · pytest

## Limits

- Free AIS comes from land-based receivers: good coverage near Europe, weak far out at sea.
- Destinations and ETAs are typed by crews and are sometimes wrong or out of date.
- Routes are simplified waypoints, not exact shipping lanes.
- Ships change speed, wait for berths and follow tides, so a calculated ETA is a sanity check, not a forecast.
- Chokepoint notes are updated by hand (`risk_zones.json`).

## Author

Mohammad Zahid Abbas · M.Sc. International Logistics & Transportation Management, UE Hamburg
