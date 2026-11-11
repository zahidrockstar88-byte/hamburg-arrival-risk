"""
app.py - The dashboard (a web page made with Streamlit).

How to run it (in the VS Code terminal):
    streamlit run app.py
Your browser opens the dashboard automatically.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pydeck as pdk
import streamlit as st

import config
from eta_model import load_model, ml_eta_for
from news import MAX_AGE_DAYS, latest_headlines
from risk import ARRIVAL_FLAGS, assess_all, is_bound_for_hamburg, is_cargo_type, nice_time, parse_time
from safety import clean_saved_ship, md, safe_link

st.set_page_config(page_title="Hamburg Arrival Risk Monitor", page_icon=":material/anchor:", layout="wide")

# How each risk flag looks: label, badge colour (Streamlit's colour names), map colour (red, green, blue, alpha).
RISK_STYLE = {
    "🔴": ("Likely late", "red", [180, 35, 24, 230]),
    "🟡": ("Check", "orange", [201, 128, 0, 230]),
    "🟢": ("On track", "green", [46, 125, 79, 230]),
    "⚫": ("In another port", "gray", [150, 150, 150, 190]),
    "⚪": ("Arriving", "violet", [120, 100, 170, 210]),
    "🔵": ("Arrived", "blue", [40, 110, 170, 210]),
}
TEXT_COLOR = {"red": "#B42318", "orange": "#B54708", "green": "#2E7D4F", "gray": "#5F6B76",
              "violet": "#5B4B8A", "blue": "#1F5F96"}
LEVEL_STYLE = {"high": ":material/error:", "medium": ":material/warning:", "low": ":material/check_circle:"}
REPO_URL = "https://github.com/zahidrockstar88-byte/hamburg-arrival-risk"

# A few small style touches the theme can't do. Static text only: no ship data ever goes in here.
st.html("""
<style>
  .block-container { padding-top: 2.2rem; max-width: 1400px; }
  .kicker { font-size: 0.78rem; letter-spacing: 0.14em; text-transform: uppercase;
            color: #0E4D64; font-weight: 600; margin-bottom: -0.6rem; }
  [data-testid="stMetricValue"], [data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; }
  [data-testid="stMetricLabel"] p { font-size: 0.82rem; color: #4A5663; }
  h3 { margin-top: 0.4rem; }
</style>
""")


# ---------------------------------------------------------------------------
# Loading data
# ---------------------------------------------------------------------------
def load_live() -> tuple[list[dict], str]:
    with open(config.LIVE_DATA_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    updated = parse_time(raw.get("meta", {}).get("updated_utc"))
    label = f"Live AIS data · collected {updated:%d %b %Y, %H:%M} UTC" if updated else "Live AIS data"
    # The file comes from radio data, so every ship is checked again before we use it (see safety.py).
    saved = raw.get("ships", {})
    ships = [clean_saved_ship(s) for s in (saved.values() if isinstance(saved, dict) else [])]
    return [s for s in ships if s], label


def load_zones() -> dict:
    with open(config.RISK_ZONES_FILE, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def cached_headlines() -> tuple[list[dict], list[str]]:
    """News is downloaded at most every 3 hours, not on every page view."""
    return latest_headlines()


NEWS_KIND_COLOR = {"Conflict / security": "red", "Accident": "red", "Closure": "orange", "Strike": "orange",
                   "Weather": "blue", "Congestion / delays": "violet", "Route update": "gray"}


def news_date(published: datetime) -> str:
    """'Today', 'Yesterday' or a date like '09 Nov'."""
    days_ago = (datetime.now(timezone.utc).date() - published.astimezone(timezone.utc).date()).days
    if days_ago == 0:
        return "Today"
    if days_ago == 1:
        return "Yesterday"
    return published.strftime("%d %b")


def ml_accuracy(model: dict | None) -> str:
    """One line comparing the ML ETA's measured error with the calculated ETA's, shown wherever ML ETAs appear."""
    if not model or model["model_mae_h"] is None or model["calculated_mae_h"] is None:
        return "ML ETA: not enough arrivals yet to measure its accuracy."
    verdict = ("more accurate" if model["model_mae_h"] < model["calculated_mae_h"]
               else "not more accurate yet, so trust the calculated ETA")
    return (f"ML ETA (experimental): average error {model['model_mae_h']:.1f} h, against "
            f"{model['calculated_mae_h']:.1f} h for the calculated ETA ({verdict}). "
            f"Learned from {model['ships']} ships.")


def badge(flag: str) -> str:
    """A coloured label for a risk flag, e.g. ':red-badge[Likely late]'. Only fixed words go inside."""
    label, color, _ = RISK_STYLE.get(flag, ("Unknown", "gray", None))
    return f":{color}-badge[{label}]"


# ---------------------------------------------------------------------------
# Sidebar: choices
# ---------------------------------------------------------------------------
now = datetime.now(timezone.utc)

with st.sidebar:
    st.subheader("Rules")
    late_threshold = st.slider("Flag as late when the difference is more than (hours)", 3, 48,
                               config.LATE_THRESHOLD_HOURS)
    stale_after = st.slider("Treat positions as too old after (hours)", 2, 72, config.STALE_AFTER_HOURS)

    st.subheader("Show")
    cargo_only = st.checkbox("Cargo ships only (AIS type 70-79)", value=True,
                             help="Container ships report as cargo ships. Ships with unknown type are kept.")
    show_arrived = st.checkbox("Ships arriving or arrived", value=True)
    containers_only = st.checkbox("Container ships only (likely)", value=False,
                                  help="A guess from the ship's name (e.g. MSC, MAERSK) or its berth at a "
                                       "container terminal. AIS does not say what a ship carries.")
    st.divider()
    st.caption("Calculated ETA = distance along the sea route ÷ speed. "
               "It is a risk flag, not a forecast.")

if not config.LIVE_DATA_FILE.exists():
    st.title("Arrival Risk Monitor")
    st.warning("No ship data yet. Run `python collector.py` to collect some.", icon=":material/sailing:")
    st.stop()

ships, source_label = load_live()
ships = [s for s in ships if is_bound_for_hamburg(s.get("destination"))]
if cargo_only:
    ships = [s for s in ships if is_cargo_type(s.get("ship_type")) is not False]   # keeps unknown types

rows = assess_all(ships, now, {"late_threshold_h": late_threshold, "stale_after_h": stale_after})
if not show_arrived:
    rows = [r for r in rows if r["Flag"] not in ARRIVAL_FLAGS]
if containers_only:
    rows = [r for r in rows if r["container_likely"]]
model = load_model()
for r in rows:
    r["ML ETA (experimental)"] = nice_time(ml_eta_for(r, model))      # "—" when there is none
df = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# Header and key numbers
# ---------------------------------------------------------------------------
st.html('<div class="kicker">Port of Hamburg · Hamburg-bound ships</div>')
st.title("Arrival Risk Monitor")
st.markdown("Cargo and container ships on their way to Hamburg, and whether the arrival time each crew "
            "reports actually fits the distance still to go.")
st.caption(f"{source_label} · page loaded {now:%d %b %Y, %H:%M} UTC")

if df.empty:
    st.warning("No ships heading to Hamburg in this data. Run the collector for longer (15+ minutes).",
               icon=":material/sailing:")
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Hamburg-bound ships", len(df), border=True)
c2.metric("Likely container ships", int(df["container_likely"].sum()), border=True,
          help="A guess from the ship's name or its berth. See Method and limits.")
c3.metric("Likely late", int((df["Flag"] == "🔴").sum()), border=True,
          help=f"Calculated ETA is more than {late_threshold} h after the ETA the crew reported.")
c4.metric("Need checking", int((df["Flag"] == "🟡").sum()), border=True,
          help="Waiting at anchor or at sea, no ETA sent, or position data too old.")
c5.metric("On track", int((df["Flag"] == "🟢").sum()), border=True)

tab_ships, tab_chokepoints, tab_method = st.tabs(["Vessels", "Chokepoints", "Method and limits"])

# ---------------------------------------------------------------------------
# Vessels: map, table, one-ship detail
# ---------------------------------------------------------------------------
with tab_ships:
    st.markdown(" ".join(badge(f) for f in RISK_STYLE) + " &nbsp; :primary-badge[Port of Hamburg]")

    map_df = df.copy()
    map_df["color"] = map_df["Flag"].map(lambda f: RISK_STYLE[f][2])
    ship_layer = pdk.Layer(
        "ScatterplotLayer", data=map_df, get_position="[lon, lat]", get_fill_color="color",
        get_line_color=[255, 255, 255, 220], line_width_min_pixels=1, stroked=True,
        get_radius=16000, radius_min_pixels=5, radius_max_pixels=13, pickable=True,
    )
    hamburg_layer = pdk.Layer(
        "ScatterplotLayer", data=pd.DataFrame([{"lat": config.HAMBURG[0], "lon": config.HAMBURG[1],
                                                "Ship": "Port of Hamburg", "Status": "", "Calculated ETA": "—"}]),
        get_position="[lon, lat]", get_fill_color=[14, 77, 100, 255], get_line_color=[255, 255, 255, 255],
        line_width_min_pixels=2, stroked=True, get_radius=22000, radius_min_pixels=8, pickable=True,
    )
    st.pydeck_chart(pdk.Deck(
        layers=[ship_layer, hamburg_layer],
        map_provider="carto", map_style="light",   # free background map, no account needed
        initial_view_state=pdk.ViewState(latitude=50.5, longitude=1.5, zoom=4.1),
        # "text" (not "html") so ship names are always shown as plain text.
        tooltip={"text": "{Ship}\n{Status}\nCalculated ETA: {Calculated ETA}",
                 "style": {"backgroundColor": "#0F2A3A", "color": "#E6EDF2", "fontSize": "12px"}},
    ), height=440)

    st.subheader("Vessel list")
    table = df.assign(Risk=df["Flag"].map(lambda f: RISK_STYLE[f][0]))
    table_cols = ["Risk", "Status", "Ship", "Container ship?", "Shipping line", "Where", "Distance (nm)",
                  "Speed (kn)", "Reported ETA", "Calculated ETA", "Difference (h)", "ML ETA (experimental)"]
    risk_colors = {label: TEXT_COLOR[color] for label, color, _ in RISK_STYLE.values()}
    styled = table[table_cols].style.map(
        lambda v: f"color: {risk_colors.get(v, '#1C2733')}; font-weight: 600", subset=["Risk"])
    st.dataframe(
        styled, hide_index=True, width="stretch",
        column_config={
            "Distance (nm)": st.column_config.NumberColumn(format="%d"),
            "Speed (kn)": st.column_config.NumberColumn(format="%.1f"),
            "Difference (h)": st.column_config.NumberColumn(
                format="%+d",
                help="Calculated ETA minus the ETA the crew reported. Positive = later than reported."),
            "Container ship?": st.column_config.TextColumn(
                help="A guess: AIS does not say what a ship carries. See the reason in the vessel detail."),
            "Shipping line": st.column_config.TextColumn(
                help="The carrier that runs the ship, guessed from its name. Container owners and cargo "
                     "owners are not public."),
            "ML ETA (experimental)": st.column_config.TextColumn(
                help="A machine-learning correction of the calculated ETA, learned from ships that really "
                     "arrived. Trained on very little data so far: see Method and limits for its accuracy."),
        },
    )

    st.caption(md(ml_accuracy(model)))

    st.subheader("Vessel detail")
    # Ship names can repeat, so we pick by row number and show the MMSI to tell them apart.
    choice = st.selectbox("Choose a vessel", range(len(df)), label_visibility="collapsed",
                          format_func=lambda i: f"{df.iloc[i]['Ship']}  ·  MMSI {df.iloc[i]['MMSI']}")
    detail = df.iloc[choice]
    # Every value that came from a ship's radio message goes through md() first (see safety.py).
    with st.container(border=True):
        st.markdown(f"### {md(detail['Ship'])}")
        st.markdown(f"{badge(detail['Flag'])} &nbsp; {md(detail['Status'])}")
        left, right = st.columns(2, gap="large")
        with left:
            st.markdown(f"**Why**  \n{md(detail['Why'])}")
            st.markdown(f"**Route ahead**  \n{md(detail['Route ahead'])}")
            st.markdown(f"**Where it came from**  \n{md(detail['Route note'])}")
        with right:
            st.markdown(f"**Container ship?**  \n{md(detail['Container verdict'])}. "
                        f"{md(detail['Container reason'])}")
            if detail["Shipping line"] != "—":
                st.markdown(f"**Shipping line** (guessed from the name)  \n{md(detail['Shipping line'])}")
            st.markdown(f"**Reported ETA** {md(detail['Reported ETA'])}  \n"
                        f"**Calculated ETA** {md(detail['Calculated ETA'])}  \n"
                        f"**ML ETA** (experimental) {md(detail['ML ETA (experimental)'])}")
            st.caption(md(ml_accuracy(model)))
        st.caption(f"Destination typed by crew: {md(detail['Destination typed'])} · Speed used: "
                   f"{md(detail['Speed used'])} · Position age: {md(detail['Position age (h)'])} h · "
                   f"MMSI {md(detail['MMSI'])}")

# ---------------------------------------------------------------------------
# Chokepoints
# ---------------------------------------------------------------------------
with tab_chokepoints:
    st.subheader("Disruptions in the news")
    st.caption(f"Headlines from the last {MAX_AGE_DAYS} days about storms, strikes, closures, congestion, accidents "
               "and conflict on the way to Hamburg. Matched by keyword from maritime news sites and Google News "
               "(no AI), refreshed every 3 hours. Click a headline for the full article.")
    headlines, failed_feeds = cached_headlines()
    groups = [("near", "Near Hamburg: can delay ships arriving in the next days"),
              ("route", "Further along the route")]
    for where, heading in groups:
        st.markdown(f"**{heading}**")
        group = [h for h in headlines if h["where"] == where]
        if not group:
            st.caption("Nothing reported.")
        for h in group:
            # Headlines come from the internet: escaped with md(), links checked by safe_link() in news.py.
            color = NEWS_KIND_COLOR.get(h["kind"], "gray")
            st.markdown(f":{color}-badge[{md(h['kind'])}] :gray-badge[{md(h['place'])}] &nbsp; "
                        f"[{md(h['title'])}]({h['link']})")
            st.caption(f"{md(h['source'])} · {md(news_date(h['published']))}")
    if failed_feeds:
        st.caption(f"Could not reach: {md(', '.join(failed_feeds))}.")

    st.subheader("Chokepoint notes")
    zones = load_zones()
    reviewed = datetime.fromisoformat(zones["last_reviewed"]).replace(tzinfo=timezone.utc)
    age_days = (now - reviewed).days
    st.markdown("Places on the way to Hamburg where conflict, closures or congestion change routes and "
                "arrival times. These notes are written by hand, not live.")
    st.caption(f"Last reviewed {reviewed:%d %b %Y}.")
    if age_days > 14:
        st.warning(f"Last reviewed {age_days} days ago. Check recent news before relying on these notes.",
                   icon=":material/schedule:")
    for z in zones["zones"]:
        with st.expander(f"{md(z['name'])} — {md(z['status'])}",
                         icon=LEVEL_STYLE.get(z["level"], ":material/help:")):
            st.markdown(md(z["effect"]))
            link = safe_link(z.get("source"))      # only plain https:// links are shown
            if link:
                st.markdown(f"[Source]({link})")

# ---------------------------------------------------------------------------
# Honest limits
# ---------------------------------------------------------------------------
with tab_method:
    how, limits = st.columns(2, gap="large")
    with how:
        st.subheader("How it works")
        st.markdown("""
1. Ships broadcast their position, speed, destination and ETA by radio (AIS). The data comes from AISStream.io.
2. We keep ships whose destination means Hamburg (for example `HAMBURG`, `DEHAM`, `NLRTM>DEHAM`).
3. We measure the distance along the usual sea route (for example Gibraltar → Ushant → Dover Strait → Elbe),
   then the River Elbe at a lower speed, plus a short buffer for the pilot and berthing.
4. Distance ÷ speed gives a **calculated ETA**. We compare it with the ETA the crew reported.
5. A big gap, an old position, a ship waiting at anchor or a missing ETA gets a flag. A ship moored in
   another port is shown as **In another port**, and a ship moored in Hamburg as **Arrived**.
6. **Container ship?** AIS only says "cargo ship". We guess "container ship" when the name starts or ends
   with a container line's word (for example `MSC`, `MAERSK`, `CMA CGM`, `EVER`), or when a ship is moored
   at a Hamburg container terminal (Waltershof, Altenwerder, Tollerort). The table shows which clue was used.
   The **shipping line comes only from the name**; a berth tells us it is a container ship, not whose.
7. **News** in the Chokepoints tab: headlines from maritime news sites and Google News (English and German).
   A headline is kept only if it names a place on the way to Hamburg **and** a disruption (storm, strike,
   closure, congestion, accident, attack), from the last 7 days. Plain keyword matching, no AI, so nothing is
   invented.
""")
        st.subheader("Experimental ML estimate")
        if model:
            a, b, c = model["coefficients"]
            better = (model["model_mae_h"] is not None and model["calculated_mae_h"] is not None
                      and model["model_mae_h"] < model["calculated_mae_h"])
            # The model file is written by a bot (see eta_model.load_model), so its values go through md() too.
            st.markdown(
                f"A straight-line model learned from **{md(model['ships'])} ships** ({md(model['examples'])} "
                f"examples) that we saw at sea and later saw moored in Hamburg, across {md(model['snapshots'])} "
                f"data snapshots:  \nreal hours ≈ {a:.2f} × calculated hours + {b:.1f} if stopped + {c:.1f}")
            st.markdown("Tested fairly: each ship is predicted by a model that never saw it.  \n"
                        + ("**" if not better else "") + md(ml_accuracy(model)) + ("**" if not better else ""))
            trained = f"{model['trained_utc']:%d %b %Y, %H:%M} UTC" if model["trained_utc"] else "unknown"
            st.caption(f"Retrained automatically after each data collection. Last trained {md(trained)}. "
                       "Arrival times are only known to within ~3 hours (the gap between snapshots), and only "
                       "ships seen arriving while we were collecting count, so long trips are under-represented.")
        else:
            st.markdown("Not enough ships have been seen arriving yet to train a model.")
    with limits:
        st.subheader("Limits")
        st.markdown("""
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
- The **ML ETA is experimental** and trained on very little data. It is shown for learning, not for planning.
- News matching is by keyword, so it can miss stories or include loosely related ones. Headlines belong to
  the news sites; we only link to them.
""")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(f"Built by Mohammad Zahid Abbas · M.Sc. International Logistics & Transportation Management, "
           f"UE Hamburg · Ship data: [AISStream.io](https://aisstream.io) · [Source code]({REPO_URL})")
