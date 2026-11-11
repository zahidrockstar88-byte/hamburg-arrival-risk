"""
app.py - The dashboard (a web page made with Streamlit).

How to run it (in the VS Code terminal):
    streamlit run app.py
Your browser opens the dashboard automatically.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pydeck as pdk
import streamlit as st

import config
from risk import assess_all, is_bound_for_hamburg, is_cargo_type, parse_time
from safety import clean_saved_ship, md, safe_link

st.set_page_config(page_title="Hamburg Arrival Risk Monitor", page_icon="🚢", layout="wide")

FLAG_COLORS = {          # map colours (red, green, blue, alpha)
    "🔴": [214, 39, 40, 220],
    "🟡": [230, 160, 0, 220],
    "🟢": [44, 160, 44, 220],
    "⚪": [120, 120, 120, 200],
}
LEVEL_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}


# ---------------------------------------------------------------------------
# Loading data
# ---------------------------------------------------------------------------
def load_demo(now: datetime) -> tuple[list[dict], str]:
    """Demo ships store times as 'minutes ago' / 'hours from now', so they never go stale."""
    with open(config.DEMO_DATA_FILE, encoding="utf-8") as f:
        raw = json.load(f)["ships"]
    ships = []
    for s in raw:
        ship = dict(s)
        ship["last_position_utc"] = (now - timedelta(minutes=s["minutes_ago"])).isoformat()
        if s.get("eta_hours_from_now") is not None:
            eta = now + timedelta(hours=s["eta_hours_from_now"])
            ship["eta"] = {"Month": eta.month, "Day": eta.day, "Hour": eta.hour, "Minute": eta.minute}
        ships.append(ship)
    return ships, "Demo data (invented ships)"


def load_live() -> tuple[list[dict], str]:
    with open(config.LIVE_DATA_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    updated = parse_time(raw.get("meta", {}).get("updated_utc"))
    label = f"Live AIS data, last collected {updated:%d %b %Y, %H:%M} UTC" if updated else "Live AIS data"
    # The file comes from radio data, so every ship is checked again before we use it (see safety.py).
    saved = raw.get("ships", {})
    ships = [clean_saved_ship(s) for s in (saved.values() if isinstance(saved, dict) else [])]
    return [s for s in ships if s], label


def load_zones() -> dict:
    with open(config.RISK_ZONES_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Sidebar: choices
# ---------------------------------------------------------------------------
now = datetime.now(timezone.utc)
live_available = config.LIVE_DATA_FILE.exists()

with st.sidebar:
    st.header("Settings")
    options = (["Live data", "Demo data"] if live_available else ["Demo data"])
    source = st.radio("Data source", options)
    if not live_available:
        st.caption("No live data yet. Run `python collector.py` to collect some.")

    late_threshold = st.slider("Flag as late when the difference is more than (hours)", 3, 48,
                               config.LATE_THRESHOLD_HOURS)
    stale_after = st.slider("Treat positions as too old after (hours)", 2, 72, config.STALE_AFTER_HOURS)
    cargo_only = st.checkbox("Cargo ships only (AIS type 70-79)", value=True,
                             help="Container ships report as cargo ships. Ships with unknown type are kept.")
    show_arrived = st.checkbox("Show ships already arriving", value=True)
    containers_only = st.checkbox("Container ships only (likely)", value=False,
                                  help="A guess from the ship's name (e.g. MSC, MAERSK) or its berth at a "
                                       "container terminal. AIS does not say what a ship carries.")

ships, source_label = load_live() if source == "Live data" else load_demo(now)
ships = [s for s in ships if is_bound_for_hamburg(s.get("destination"))]
if cargo_only:
    ships = [s for s in ships if is_cargo_type(s.get("ship_type")) is not False]   # keeps unknown types

rows = assess_all(ships, now, {"late_threshold_h": late_threshold, "stale_after_h": stale_after})
if not show_arrived:
    rows = [r for r in rows if r["Flag"] != "⚪"]
if containers_only:
    rows = [r for r in rows if r["container_likely"]]
df = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# Header and key numbers
# ---------------------------------------------------------------------------
st.title("🚢 Hamburg Arrival Risk Monitor")
st.caption(f"Container and cargo ships heading to the Port of Hamburg · {source_label} · "
           f"page loaded {now:%d %b %Y, %H:%M} UTC")
if source == "Demo data":
    st.info("You are looking at **demo data**: invented ships that show how each flag works. "
            "Switch to live data in the sidebar once you have run the collector.")

if df.empty:
    st.warning("No ships heading to Hamburg in this data. Run the collector for longer (15+ minutes).")
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Ships heading to Hamburg", len(df))
c2.metric("📦 Likely container ships", int(df["container_likely"].sum()))
c3.metric("🔴 Likely late", int((df["Flag"] == "🔴").sum()))
c4.metric("🟡 Need checking", int((df["Flag"] == "🟡").sum()))
c5.metric("🟢 On track", int((df["Flag"] == "🟢").sum()))

# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
map_df = df.copy()
map_df["color"] = map_df["Flag"].map(FLAG_COLORS)
ship_layer = pdk.Layer(
    "ScatterplotLayer", data=map_df, get_position="[lon, lat]", get_fill_color="color",
    get_radius=18000, radius_min_pixels=5, radius_max_pixels=14, pickable=True,
)
hamburg_layer = pdk.Layer(
    "ScatterplotLayer", data=pd.DataFrame([{"lat": config.HAMBURG[0], "lon": config.HAMBURG[1],
                                            "Ship": "Port of Hamburg", "Status": "", "Calculated ETA": ""}]),
    get_position="[lon, lat]", get_fill_color=[30, 90, 200, 255], get_radius=25000,
    radius_min_pixels=7, pickable=True,
)
st.pydeck_chart(pdk.Deck(
    layers=[ship_layer, hamburg_layer],
    map_provider="carto", map_style="light",   # free background map, no account needed
    initial_view_state=pdk.ViewState(latitude=47, longitude=-2, zoom=3.3),
    tooltip={"text": "{Ship}\n{Status}\nCalculated ETA: {Calculated ETA}"},
), height=430)

# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------
st.subheader("Ships and their arrival risk")
table_cols = ["Flag", "Status", "Ship", "Container ship?", "Shipping line", "Where", "Distance (nm)",
              "Speed (kn)", "Reported ETA", "Calculated ETA", "Difference (h)"]
st.dataframe(
    df[table_cols], hide_index=True, width="stretch",
    column_config={
        "Difference (h)": st.column_config.NumberColumn(
            help="Calculated ETA minus the ETA the crew reported. Positive = later than reported."),
        "Container ship?": st.column_config.TextColumn(
            help="A guess: AIS does not say what a ship carries. See the reason below the table."),
        "Shipping line": st.column_config.TextColumn(
            help="The carrier that runs the ship, guessed from its name. Container owners and cargo "
                 "owners are not public."),
    },
)

# Ship names can repeat, so we pick by row number and show the MMSI to tell them apart.
choice = st.selectbox("See the reasoning for one ship", range(len(df)),
                      format_func=lambda i: f"{df.iloc[i]['Ship']} (MMSI {df.iloc[i]['MMSI']})")
detail = df.iloc[choice]
# Every value that came from a ship's radio message goes through md() first (see safety.py).
with st.container(border=True):
    st.markdown(f"### {md(detail['Flag'])} {md(detail['Ship'])} · {md(detail['Status'])}")
    st.markdown(f"**Why:** {md(detail['Why'])}")
    st.markdown(f"**Container ship?** {md(detail['Container ship?'])} · {md(detail['Container reason'])}")
    if detail["Shipping line"] != "—":
        st.markdown(f"**Shipping line (guessed from the name):** {md(detail['Shipping line'])}")
    st.markdown(f"**Route ahead:** {md(detail['Route ahead'])}")
    st.markdown(f"**Where it came from:** {md(detail['Route note'])}")
    st.caption(f"Destination typed by crew: {md(detail['Destination typed'])} · Speed used: {md(detail['Speed used'])} · "
               f"Position age: {md(detail['Position age (h)'])} h · MMSI {md(detail['MMSI'])}")

# ---------------------------------------------------------------------------
# Chokepoints
# ---------------------------------------------------------------------------
zones = load_zones()
st.subheader("Chokepoints and risks on the way to Hamburg")
reviewed = datetime.fromisoformat(zones["last_reviewed"]).replace(tzinfo=timezone.utc)
age_days = (now - reviewed).days
st.caption(f"Notes last reviewed by hand on {reviewed:%d %b %Y}.")
if age_days > 14:
    st.warning(f"These notes are {age_days} days old. Update risk_zones.json.")
for z in zones["zones"]:
    with st.expander(f"{LEVEL_ICON.get(z['level'], '⚪')} {md(z['name'])}: {md(z['status'])}"):
        st.markdown(md(z["effect"]))
        link = safe_link(z.get("source"))      # only plain https:// links are shown
        if link:
            st.markdown(f"[Source]({link})")

# ---------------------------------------------------------------------------
# Honest limits
# ---------------------------------------------------------------------------
with st.expander("How this works, and its limits"):
    st.markdown("""
**How it works**
1. Ships broadcast their position, speed, destination and ETA by radio (AIS). The data comes from AISStream.io.
2. We keep ships whose destination means Hamburg (for example `HAMBURG`, `DEHAM`, `NLRTM>DEHAM`).
3. We measure the distance along the usual sea route (for example Gibraltar → Ushant → Dover Strait → Elbe),
   then the River Elbe at a lower speed, plus a short buffer for the pilot and berthing.
4. Distance ÷ speed gives a **calculated ETA**. We compare it with the ETA the crew reported.
5. A big gap, an old position or a stopped ship gets a flag.
6. **Container ship?** AIS only says "cargo ship". We guess "container ship" when the name starts or ends
   with a container line's word (for example `MSC`, `MAERSK`, `CMA CGM`, `EVER`), or when a ship is moored
   at a Hamburg container terminal (Waltershof, Altenwerder, Tollerort). The table shows which clue was used.
   The **shipping line comes only from the name**; a berth tells us it is a container ship, not whose.

**Limits**
- This is a **risk flag, not a precise ETA prediction.** Ships change speed, wait for berths and follow tides.
- Free AIS data comes from land-based receivers. Coverage is good near Europe and weak far out at sea.
- Crews type destination and ETA by hand. Some are wrong or out of date.
- Routes are simplified waypoints, not exact shipping lanes.
- Chokepoint notes are updated by hand, not live.
- "Container ship" and "Shipping line" are **guesses**. Ships can be renamed or chartered to another line,
  and some words (like `EXPRESS` or `ONE`) are also used by other ships, so they only count for ships that
  report a cargo type. "Unlikely" is based on the ship type the crew set, which can be wrong.
  Terminal areas are approximate.
- **Who owns the containers or the cargo is not public.** Containers are often leased from companies such as
  Triton or Textainer, and cargo owners appear only in confidential shipping documents (bills of lading).
  AIS never carries this information.
- Ship names and destinations are typed by crews and can contain anything, so the dashboard shows them as
  plain text only.
""")
