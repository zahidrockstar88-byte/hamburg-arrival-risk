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
6. Guesses which ships are **container ships**, from the ship's name or its berth at a Hamburg container
   terminal, and which **shipping line** runs them (MSC, Maersk, CMA CGM, Evergreen, Hapag-Lloyd, ...),
   from the name only. The table shows which clue each guess is based on.
7. Shows chokepoint risks on the way (Red Sea, Hormuz, North European congestion), with the **latest
   maritime news headlines** about them from public RSS feeds (keyword matching, no AI).
8. Adds an **experimental machine-learning ETA**: a simple model that learns from ships that really arrived
   (rebuilt from the git history of `data/ships.json`), retrained after every collection, and tested with
   leave-one-ship-out. Its measured error is shown next to the plain calculation's
   ([eta_model.py](eta_model.py)).

9. **Shipping-line scorecard** (procurement view): rebuilds real arrivals of cargo ships from the saved
   history and shows which shipping lines berth within a day of the ETA they first reported
   ([history.py](history.py)).
10. **After the berth**: estimates unloading time, when containers are ready for pickup, when they could
    leave by train or reach your warehouse by truck, as ranges from stated assumptions
    ([operations.py](operations.py)).
11. **Cost of delay**: ship time from the New ConTex charter index plus the capital tied up in delayed cargo
    (Sea-Intelligence benchmark), in US dollars, as low–high ranges.
12. **Routes from Asia**: for 25 Asian ports (China, Korea, Japan, Taiwan, Southeast Asia, India, Sri Lanka,
    Pakistan, Bangladesh, the Gulf), the distance to Hamburg via the Suez Canal and around the Cape of Good Hope
    (searoute, calibrated to published figures), and what the detour adds in days, fuel, CO₂, EU ETS, ship time
    and Suez toll, with a "Red Sea closed" switch and the extra ships a weekly service needs ([voyage.py](voyage.py)).
13. **CO₂ and EU ETS** for each container ship's remaining trip, and what sailing 2 knots slower would save.

## Security

AIS messages are broadcast by radio, so anyone can send any text as a ship name or destination.
The project treats all of it as untrusted ([safety.py](safety.py)):

- The collector keeps only characters the AIS standard allows, cuts text to its official length and checks
  that numbers (ship type, IMO, position, speed, ETA) are real numbers in their AIS range.
- Saved data is checked again every time it is loaded, so records from older versions are cleaned too.
- The dashboard escapes every ship-supplied value, so a name like `[CLICK](HTTP://X.CO)` stays plain text.
- Only `https://` links are shown for chokepoint sources and news.
- News feeds are read with `defusedxml` (blocks XML attacks), with a time and size limit; headlines are
  cleaned to plain text.
- The API key lives only in `.env` (ignored by git) and in encrypted GitHub Actions secrets.
- The GitHub Action is pinned to exact commit IDs and has only the permission it needs.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py          # shows the latest ships saved in data/ships.json, no key needed
```

For live data, add a free AISStream key to `.env` (see `.env.example`), then:

```bash
python collector.py --minutes 15
```

Full beginner steps: [SETUP_GUIDE.md](SETUP_GUIDE.md) · How the logic works: [HOW_IT_WORKS.md](HOW_IT_WORKS.md)

## Built with

Python · Streamlit · pydeck · NumPy · AISStream.io websocket API · RSS (defusedxml) · GitHub Actions · pytest

## Limits

- Free AIS comes from land-based receivers: good coverage near Europe, weak far out at sea.
- Destinations and ETAs are typed by crews and are sometimes wrong or out of date.
- Routes are simplified waypoints, not exact shipping lanes.
- Ships change speed, wait for berths and follow tides, so a calculated ETA is a sanity check, not a forecast.
- Chokepoint notes are updated by hand (`risk_zones.json`).
- "Container ship" and "shipping line" are educated guesses: AIS does not say what a ship carries, and ships
  can be renamed or chartered. Who leases the containers or owns the cargo is not public (it is in
  confidential bills of lading), so the dashboard does not show it.
- The ML ETA is experimental: it is trained on few arrivals, and arrival times are only known to within the
  ~3 hours between snapshots. The dashboard shows its measured error and keeps the calculated ETA as the main number.
- News is matched by keyword, so it can miss stories or include loosely related ones.
- Shipping-line scores are measured against the ETA a ship reported when we first saw it (usually a day or two out),
  not the published schedule, so they are higher than industry reliability reports. Few arrivals per line so far.
- Route distances come from a shipping-lane network, not real tracks; fuel and CO₂ use published averages and
  the cube-of-speed rule; the Suez toll is a rough estimate (no official per-size table could be verified).
- Unloading times and delay costs are estimates from published averages and stated assumptions (see
  `config.py`), not terminal or contract data.

## Author

Mohammad Zahid Abbas · M.Sc. International Logistics & Transportation Management, UE Hamburg
