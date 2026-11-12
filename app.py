"""
app.py - The dashboard (a web page made with Streamlit).

How to run it (in the VS Code terminal):
    streamlit run app.py
Your browser opens the dashboard automatically.

Look and feel: a nautical chart of the Elbe. Risk colours are the river's own buoys
(red can = likely late, yellow special mark = check, green cone = on track), and the
centrepiece is the approach to Hamburg: every ship placed by its distance to the berth.
"""

from __future__ import annotations

import json
from typing import NamedTuple
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

# Streamlit re-runs app.py after every upload but can keep OLD copies of our helper files in memory, which once
# broke the live site ("ImportError" for a name that only exists in the new risk.py). So reload our own files
# first, in the order they depend on each other. Outside libraries (streamlit, pandas...) are not touched.
import importlib
import sys

for _module in ("config", "safety", "risk", "news", "history", "operations", "voyage", "eta_model"):
    if _module in sys.modules:
        importlib.reload(sys.modules[_module])

# These imports come after the reload loop on purpose, so the "imports at the top" rule (E402) is switched off here.
import config  # noqa: E402
from eta_model import load_model, ml_eta_for  # noqa: E402
from history import UNKNOWN_LINE, judge, load_arrivals, scorecard  # noqa: E402
from news import MAX_AGE_DAYS, latest_headlines  # noqa: E402
from risk import (ARRIVAL_FLAGS, ARRIVED, ARRIVING, CHART_FLAGS, CHECK, IN_ANOTHER_PORT, LIKELY_LATE,  # noqa: E402
                  NO_ETA_TO_JUDGE, ON_TRACK, assess_all, is_bound_for_hamburg, is_cargo_type, nice_time,
                  parse_time, usable_speed)
from operations import after_berth, delay_cost, estimate_teu, money_range, total_cost  # noqa: E402
from safety import clean_saved_ship, md, safe_link  # noqa: E402
from voyage import compare_routes, load_asia_routes, red_sea_closed_by_region, slower_by, voyage_emissions  # noqa: E402

st.set_page_config(page_title="Hamburg Arrival Risk Monitor", page_icon=":material/anchor:", layout="wide")

# Colours, checked with the dataviz skill's colour-blind validator. Red and green are told apart by
# shape as well (square can, triangle cone), the way buoys are on the river.
NAVY, CHART_WHITE, WATER, RULE = "#12324A", "#F4F8F9", "#E3EEF2", "#C9DAE1"
class RiskStyle(NamedTuple):
    label: str          # the word shown to people
    badge: str          # Streamlit badge colour name
    text_color: str     # colour for the word in the table
    map_rgba: list      # dot colour on the map (red, green, blue, opacity)
    shape: str          # marker shape on the approach chart


RISK_STYLE = {   # flag code (from risk.py) -> how it looks
    "🔴": RiskStyle("Likely late", "red", "#C1272D", [193, 39, 45, 235], "square"),
    "🟡": RiskStyle("Check", "orange", "#8A6100", [224, 168, 0, 235], "diamond"),
    "🟢": RiskStyle("On track", "green", "#00866E", [0, 134, 110, 235], "triangle-up"),
    "⚫": RiskStyle("In another port", "gray", "#5E7180", [138, 154, 166, 210], "circle"),
    "⚪": RiskStyle("Arriving", "blue", "#0F5C80", [15, 92, 128, 220], "circle"),
    "🔵": RiskStyle("Arrived", "primary", NAVY, [18, 50, 74, 220], "circle"),
}
MARK_COLOR = {"🔴": "#C1272D", "🟡": "#E0A800", "🟢": "#00866E", "⚫": "#8A9AA6"}   # chart marks only
LEVEL_STYLE = {"high": ":material/error:", "medium": ":material/warning:", "low": ":material/check_circle:"}
REPO_URL = "https://github.com/zahidrockstar88-byte/hamburg-arrival-risk"

# Landmarks on the approach, as distance to the berth along the route (nm), from risk.route_to_hamburg().
LANDMARKS = [("Gibraltar", 1529), ("Ushant", 685), ("Dover Strait", 376), ("Elbe 1", 75),
             ("Cuxhaven", 52), ("Brunsbüttel", 38), ("Wedel", 11), ("Berth", 0)]

# A few small style touches the theme can't do. Static text only: no ship data ever goes in here.
st.html("""
<style>
  .block-container { padding-top: 2.4rem; max-width: 1240px; }
  h1 { line-height: 1.05; letter-spacing: -0.01em; max-width: 32ch; }
  [data-testid="stDataFrame"], [data-testid="stVegaLiteChart"] { font-variant-numeric: tabular-nums; }
  .stMarkdown p { max-width: 78ch; }
  a:focus-visible, button:focus-visible, [role="tab"]:focus-visible, input:focus-visible {
    outline: 2px solid #0F5C80; outline-offset: 2px; }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
</style>
""")


# ---------------------------------------------------------------------------
# Loading data
# ---------------------------------------------------------------------------
def load_live() -> tuple[list[dict], datetime | None]:
    with open(config.LIVE_DATA_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    updated = parse_time(raw.get("meta", {}).get("updated_utc"))
    # The file comes from radio data, so every ship is checked again before we use it (see safety.py).
    saved = raw.get("ships", {})
    ships = [clean_saved_ship(s) for s in (saved.values() if isinstance(saved, dict) else [])]
    return [s for s in ships if s], updated


def load_zones() -> dict:
    with open(config.RISK_ZONES_FILE, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def cached_headlines() -> tuple[list[dict], list[str]]:
    """News is downloaded at most every 3 hours, not on every page view."""
    return latest_headlines()


def news_date(published: datetime) -> str:
    """'today', 'yesterday' or a date like '9 Nov'."""
    days_ago = (datetime.now(timezone.utc).date() - published.astimezone(timezone.utc).date()).days
    if days_ago == 0:
        return "today"
    if days_ago == 1:
        return "yesterday"
    return f"{published.day} {published:%b}"


def ml_accuracy(model: dict | None) -> str:
    """One line comparing the ML ETA's measured error with the calculated ETA's, shown wherever ML ETAs appear."""
    if not model or model["model_mae_h"] is None or model["calculated_mae_h"] is None:
        return "The ML ETA needs more arrivals before its accuracy can be measured."
    verdict = "more accurate" if ml_is_better(model) else "not more accurate yet, so trust the calculated ETA"
    return (f"The experimental ML ETA is off by {model['model_mae_h']:.1f} h on average, against "
            f"{model['calculated_mae_h']:.1f} h for the calculated ETA ({verdict}). "
            f"It learned from {model['ships']} ships.")


def range_text(low: float, high: float) -> str:
    """A (low, high) range as plain text, e.g. "1,200 to 1,650". One value if both ends round the same."""
    low_text, high_text = f"{low:,.0f}", f"{high:,.0f}"
    return low_text if low_text == high_text else f"{low_text} to {high_text}"


def headline_markdown(headline: dict) -> str:
    """One news headline as text: kind, place, linked title. Escaped with md(); the link was checked in news.py."""
    return (f":gray-badge[{md(headline['kind'])}] **{md(headline['place'])}.** "
            f"[{md(headline['title'])}]({headline['link']})")


def ml_is_better(model: dict | None) -> bool:
    """True when the ML ETA's measured error is smaller than the calculated ETA's."""
    return bool(model and model["model_mae_h"] is not None and model["calculated_mae_h"] is not None
                and model["model_mae_h"] < model["calculated_mae_h"])


def badge(flag: str) -> str:
    """A coloured label for a risk flag, e.g. ':red-badge[Likely late]'. Only fixed words go inside."""
    style = RISK_STYLE.get(flag)
    return f":{style.badge}-badge[{style.label}]" if style else ":gray-badge[Unknown]"


def headline_sentence(late: int, total: int) -> str:
    """The page's headline: the answer itself, in one sentence."""
    if late == 0:
        return f"None of the {total} ships bound for Hamburg look likely to berth late."
    verb = "looks" if late == 1 else "look"
    return f"{late} of {total} ships bound for Hamburg {verb} likely to berth late."


def approach_chart(df: pd.DataFrame) -> alt.LayerChart:
    """
    The approach to Hamburg: one lane per risk, every ship placed by its distance to the berth
    (log scale, so the river is readable next to the open sea). The berth is on the right.
    """
    lanes = [f for f in CHART_FLAGS if (df["Flag"] == f).any()]
    ships = df[df["Flag"].isin(lanes)].copy()
    lane_names = [f"{RISK_STYLE[f].label} ({(df['Flag'] == f).sum()})" for f in lanes]
    # Each lane is a row number (0 = top). Ships at the same distance would sit on top of each other, so each
    # one is nudged up or down a little. The nudge comes from the ship's MMSI number (its remainder after
    # dividing by 97), so the same ship always gets the same nudge and the chart doesn't jump on every reload.
    ships["Row"] = ships["Flag"].map(lanes.index) + ships["MMSI"].map(
        lambda m: ((int(m) % 97) / 97 - 0.5) * 0.5 if str(m).isdigit() else 0.0)
    ships["Miles"] = ships["Distance (nm)"].clip(lower=0)

    far = max(1600, int(ships["Miles"].max() or 0) + 100)
    x = alt.X("Miles:Q", title=None, axis=None,
              scale=alt.Scale(type="symlog", constant=20, domain=[far, 0]))
    # The chart library draws the lane names from a tiny JavaScript list, e.g. ['Likely late (5)','Check (9)'][row].
    # Only our own fixed words and counts go into it, never ship data.
    label_expr = "[" + ",".join(f"'{name}'" for name in lane_names) + "][datum.value]"
    y = alt.Y("Row:Q", title=None, scale=alt.Scale(domain=[len(lanes) - 0.45, -0.55], nice=False),
              axis=alt.Axis(values=list(range(len(lanes))), labelExpr=label_expr, grid=False, ticks=False,
                            domain=False, labelFontSize=15, labelColor=NAVY, labelPadding=14,
                            labelFont="Barlow Condensed", labelFontWeight=600))
    marks = alt.Chart(ships).mark_point(filled=True, size=170, opacity=0.95, stroke=CHART_WHITE,
                                        strokeWidth=2).encode(
        x=x, y=y,
        color=alt.Color("Flag:N", legend=None,
                        scale=alt.Scale(domain=list(MARK_COLOR), range=list(MARK_COLOR.values()))),
        shape=alt.Shape("Flag:N", legend=None,
                        scale=alt.Scale(domain=list(MARK_COLOR), range=[RISK_STYLE[f].shape for f in MARK_COLOR])),
        tooltip=[alt.Tooltip("Ship:N"), alt.Tooltip("Status:N"),
                 alt.Tooltip("Distance (nm):Q", title="Distance to berth (nm)"),
                 alt.Tooltip("Calculated ETA:N"), alt.Tooltip("Reported ETA:N")],
    )
    marks_df = pd.DataFrame(LANDMARKS, columns=["Name", "Miles"])
    rules = alt.Chart(marks_df).mark_rule(color=RULE, strokeWidth=1).encode(x=x)
    upper = marks_df[marks_df["Name"].isin(["Elbe 1", "Brunsbüttel", "Berth"])]       # second label row
    lower = marks_df[~marks_df["Name"].isin(upper["Name"])]
    label = dict(align="center", baseline="bottom", color="#45627A", fontSize=12, font="Barlow")
    names_low = alt.Chart(lower).mark_text(dy=-6, **label).encode(x=x, y=alt.value(0), text="Name:N")
    names_high = alt.Chart(upper).mark_text(dy=-22, **label).encode(x=x, y=alt.value(0), text="Name:N")
    return (alt.layer(rules, marks, names_low, names_high)
            .properties(height=62 * len(lanes) + 10, padding={"top": 42, "left": 6, "right": 22, "bottom": 6})
            .configure(font="Barlow", background=CHART_WHITE)
            .configure_view(fill=WATER, stroke=None))


# ---------------------------------------------------------------------------
# Sidebar: choices
# ---------------------------------------------------------------------------
now = datetime.now(timezone.utc)

with st.sidebar:
    st.subheader("Rules")
    late_threshold = st.slider("Call a ship late when it is more than this many hours behind", 3, 48,
                               config.LATE_THRESHOLD_HOURS)
    stale_after = st.slider("Stop trusting a position after (hours)", 2, 72, config.STALE_AFTER_HOURS)

    st.subheader("Show")
    cargo_only = st.checkbox("Cargo ships only (AIS type 70-79)", value=True,
                             help="Container ships report as cargo ships. Ships with unknown type are kept.")
    show_arrived = st.checkbox("Ships arriving or arrived", value=True)
    containers_only = st.checkbox("Container ships only (likely)", value=False,
                                  help="A guess from the ship's name (e.g. MSC, MAERSK) or its berth at a "
                                       "container terminal. AIS does not say what a ship carries.")
    st.subheader("Scenario")
    red_sea_closed = st.toggle("Red Sea closed", help="What if no ship can use the Suez Canal and every voyage from "
                               "Asia must go around Africa? See the Ships and Routes from Asia tabs.")
    st.subheader("After the berth")
    warehouse_km = st.slider("Distance from the terminal to your warehouse (km)", 5, 150,
                             config.DEFAULT_WAREHOUSE_KM, step=5,
                             help="Used to estimate when containers from a ship could reach your warehouse by truck.")
    st.divider()
    st.caption("The calculated ETA is the distance along the sea route divided by the ship's speed. "
               "The flags are warnings, not forecasts.")

if not config.LIVE_DATA_FILE.exists():
    st.title("No ship data yet")
    st.warning("Run `python collector.py` to collect positions, then reload this page.", icon=":material/sailing:")
    st.stop()

ships, updated = load_live()
ships = [s for s in ships if is_bound_for_hamburg(s.get("destination"))]
if cargo_only:
    ships = [s for s in ships if is_cargo_type(s.get("ship_type")) is not False]   # keeps unknown types

rows = assess_all(ships, now, {"late_threshold_h": late_threshold, "stale_after_h": stale_after})
if not show_arrived:
    rows = [row for row in rows if row["Flag"] not in ARRIVAL_FLAGS]
if containers_only:
    rows = [row for row in rows if row["container_likely"]]
model = load_model()
for row in rows:
    row["ML ETA (experimental)"] = nice_time(ml_eta_for(row, model))      # "—" when there is none
    # Size and delay cost are only estimated for likely container ships: the assumptions are about containers.
    teu, size_basis = (None, "")
    if row["container_likely"]:
        teu, size_basis = estimate_teu(row["length_m"])
    row["teu"] = teu
    row["size_basis"] = size_basis
    row["Size (TEU, est.)"] = f"~{teu:,}" if teu else "—"
    # Delay = calculated ETA minus the ETA the crew reports now (see "Delay cost" in GLOSSARY.md).
    late_by = row["Difference (h)"] if row["Flag"] == LIKELY_LATE else None
    row["cost"] = delay_cost(teu, late_by) if teu and late_by else None
    row["CO2 to go (t, est.)"] = "—"
    if teu and row["Flag"] not in NO_ETA_TO_JUDGE:
        trip = voyage_emissions(teu, usable_speed(row["Speed (kn)"]), row["Distance (nm)"],
                                config.ETS_SHARE_FROM_OUTSIDE_EU)   # the share changes the ETS cost, not the CO2
        row["CO2 to go (t, est.)"] = range_text(*trip["co2_t"])
df = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# Headline: the answer, then the approach to Hamburg
# ---------------------------------------------------------------------------
if df.empty:
    st.title("No ships bound for Hamburg in this data")
    st.warning("Collect for longer (15 minutes or more) so ships have time to send their destination.",
               icon=":material/sailing:")
    st.stop()

def count(flag: str) -> int:
    return int((df["Flag"] == flag).sum())

st.title(md(headline_sentence(count(LIKELY_LATE), len(df))))
st.markdown(md(f"{count(CHECK)} need a closer look, {count(ON_TRACK)} are on track, {count(IN_ANOTHER_PORT)} are "
            f"still in another port and {count(ARRIVING) + count(ARRIVED)} have reached or are reaching Hamburg. "
            f"{int(df['container_likely'].sum())} of the {len(df)} are likely container ships."))
st.caption(md(f"Ship positions collected {updated:%d %b %Y at %H:%M} UTC." if updated else "Ship positions from AIS."))

if df["Flag"].isin(CHART_FLAGS).any():
    st.altair_chart(approach_chart(df), width="stretch", theme=None)
    st.caption("Distance to the berth along the sea route, on a log scale so the river and the open sea both fit. "
               "Hover over a ship for its name and ETAs.")

# What could hold ships up: the newest disruptions, near Hamburg first (full list in the tab).
headlines, failed_feeds = cached_headlines()
top_news = sorted(headlines, key=lambda item: item["where"] != "near")[:3]   # near Hamburg first, then newest
st.subheader("What could hold ships up")
if not top_news:
    st.caption(f"No disruptions on the way to Hamburg reported in the last {MAX_AGE_DAYS} days.")
for headline in top_news:
    # Headlines come from the internet: escaped with md(), links checked by safe_link() in news.py.
    st.markdown(f"{headline_markdown(headline)} "
                f"({md(headline['source'])}, {md(news_date(headline['published']))})")

tab_ships, tab_lines, tab_routes, tab_news, tab_method = st.tabs(
    ["Ships", "Shipping lines", "Routes from Asia", "News and disruptions", "How it works"])

# ---------------------------------------------------------------------------
# Ships: map, table, one-ship detail
# ---------------------------------------------------------------------------
with tab_ships:
    if red_sea_closed:
        regions = red_sea_closed_by_region(load_asia_routes(), config.ROUTE_DEFAULT_TEU, config.ROUTE_DEFAULT_SPEED_KN)

        def days_text(days: tuple) -> str:
            low, high = f"{days[0]:.1f}", f"{days[1]:.1f}"
            return f"{low} days" if low == high else f"{low} to {high} days"

        region_text = "; ".join(f"{region} {days_text(r['days'])} later and {money_range(*r['cost_usd'])} per voyage"
                                for region, r in sorted(regions.items()))
        via_med = sum(1 for s in ships if s.get("seen_in_mediterranean"))
        if via_med == 0:
            med_text = "None of them was seen coming through the Mediterranean."
        elif via_med == 1:
            med_text = ("1 of them came through the Mediterranean, possibly via Suez; its next voyage from Asia "
                        "would go around Africa.")
        else:
            med_text = (f"{via_med} of them came through the Mediterranean, possibly via Suez; their next voyages "
                        f"from Asia would go around Africa.")
        st.info(md(f"Red Sea closed: the ships on this page are already in European waters, so their ETAs don't "
                   f"change. {med_text} New arrivals from Asia: {region_text} (extra fuel, EU ETS cost and ship time, "
                   f"minus the Suez toll saved; a {config.ROUTE_DEFAULT_TEU:,} TEU ship at "
                   f"{config.ROUTE_DEFAULT_SPEED_KN} knots; details in Routes from Asia)."),
                icon=":material/route:")
    st.markdown(" ".join(badge(f) for f in RISK_STYLE) + " &nbsp; :gray-badge[Port of Hamburg]")

    map_df = df.copy()
    map_df["color"] = map_df["Flag"].map(lambda f: RISK_STYLE[f].map_rgba)
    ship_layer = pdk.Layer(
        "ScatterplotLayer", data=map_df, get_position="[lon, lat]", get_fill_color="color",
        get_line_color=[244, 248, 249, 255], line_width_min_pixels=1.5, stroked=True,
        get_radius=16000, radius_min_pixels=5, radius_max_pixels=13, pickable=True,
    )
    hamburg_layer = pdk.Layer(
        "ScatterplotLayer", data=pd.DataFrame([{"lat": config.HAMBURG[0], "lon": config.HAMBURG[1],
                                                "Ship": "Port of Hamburg", "Status": "", "Calculated ETA": "—"}]),
        get_position="[lon, lat]", get_fill_color=[244, 248, 249, 255], get_line_color=[18, 50, 74, 255],
        line_width_min_pixels=3, stroked=True, get_radius=22000, radius_min_pixels=8, pickable=True,
    )
    st.pydeck_chart(pdk.Deck(
        layers=[ship_layer, hamburg_layer],
        map_provider="carto", map_style="light",   # free background map, no account needed
        initial_view_state=pdk.ViewState(latitude=50.5, longitude=1.5, zoom=4.1),
        # "text" (not "html") so ship names are always shown as plain text.
        tooltip={"text": "{Ship}\n{Status}\nCalculated ETA: {Calculated ETA}",
                 "style": {"backgroundColor": NAVY, "color": CHART_WHITE, "fontSize": "12px"}},
    ), height=440)

    st.subheader("Every ship")
    table = df.assign(Risk=df["Flag"].map(lambda f: RISK_STYLE[f].label))
    table_cols = ["Risk", "Status", "Ship", "Container ship?", "Shipping line", "Where", "Distance (nm)",
                  "CO2 to go (t, est.)",
                  "Speed (kn)", "Reported ETA", "Calculated ETA", "Difference (h)", "ML ETA (experimental)"]
    risk_colors = {style.label: style.text_color for style in RISK_STYLE.values()}
    styled = table[table_cols].style.map(
        lambda v: f"color: {risk_colors.get(v, NAVY)}; font-weight: 600", subset=["Risk"])
    st.dataframe(
        styled, hide_index=True, width="stretch",
        column_config={
            "Distance (nm)": st.column_config.NumberColumn(format="%d"),
            "Speed (kn)": st.column_config.NumberColumn(format="%.1f"),
            "Difference (h)": st.column_config.NumberColumn(
                format="%+d",
                help="Calculated ETA minus the ETA the crew reported. Positive means later than reported."),
            "Container ship?": st.column_config.TextColumn(
                help="A guess: AIS does not say what a ship carries. The reason is in the ship's details below."),
            "Shipping line": st.column_config.TextColumn(
                help="The shipping line that runs the ship, guessed from its name. Container owners and cargo "
                     "owners are not public."),
            "ML ETA (experimental)": st.column_config.TextColumn(
                help="A machine-learning correction of the calculated ETA, learned from ships that really "
                     "berthed. Its accuracy is shown below the table."),
        },
    )
    st.caption(md(ml_accuracy(model)))

    st.subheader("Delay cost of the late ships")
    costed = df[df["cost"].notna()] if "cost" in df else df.iloc[0:0]
    late_containers = int(((df["Flag"] == LIKELY_LATE) & df["container_likely"]).sum())
    unsized = df[(df["Flag"] == LIKELY_LATE) & df["container_likely"] & df["cost"].isna()]["Ship"].tolist()
    if late_containers == 0:
        st.markdown("No likely container ship is running late right now, so there is no delay cost to estimate.")
    elif not costed.empty:
        total_low, total_high = total_cost(list(costed["cost"]))
        ships_word = "ship we can size is" if len(costed) == 1 else "ships we can size are"
        st.markdown(md(f"The {len(costed)} late container {ships_word} costing roughly "
                       f"{money_range(total_low, total_high)} in ship time and tied-up cargo."))
    if unsized:
        its, their = ("its", "its") if len(unsized) == 1 else ("their", "their")
        st.markdown(md(f"No cost yet for {', '.join(unsized)}: {its} length hasn't been reported, so {their} size "
                       "(and so the charter rate) is unknown."))
    if not costed.empty:
        cost_table = pd.DataFrame([{
            "Ship": r["Ship"], "Shipping line": r["Shipping line"], "Late by (h)": r["Difference (h)"],
            "Size (TEU, est.)": r["Size (TEU, est.)"], "Ship time": money_range(*r["cost"]["ship"]),
            "Tied-up cargo": money_range(*r["cost"]["cargo"]), "Total": money_range(*r["cost"]["total"]),
            "Ship rate from": r["cost"]["rate_basis"],
        } for _, r in costed.iterrows()])
        st.dataframe(cost_table, hide_index=True, width="stretch",
                     column_config={"Late by (h)": st.column_config.NumberColumn(format="%d")})
    st.caption("Late = the calculated ETA is more than the late limit after the ETA the crew reports now. "
               "Ship time = the daily charter rate for a ship of that size times the days late: New ConTex index "
               "(Aug to Oct 2026) up to 4,250 TEU, our labelled estimate above that. Tied-up cargo = the value "
               "of the containers unloaded in Hamburg ($40,000 per TEU, Sea-Intelligence benchmark) at 5 to 10 % "
               "a year. Fuel is left out (a waiting ship burns little). Demurrage and detention are left out on "
               "purpose: they are fees for containers left at the terminal or returned late, after unloading, so "
               "a late ship doesn't cause them. Estimates, in US dollars.")

    st.subheader("One ship in detail")
    # Ship names can repeat, so we pick by row number and show the MMSI to tell them apart.
    choice = st.selectbox("Choose a ship", range(len(df)),
                          format_func=lambda i: f"{df.iloc[i]['Ship']} (MMSI {df.iloc[i]['MMSI']})")
    detail = df.iloc[choice]
    # In a table, a missing size becomes NaN ("not a number"), which Python treats as true, so check it properly.
    detail_teu = None if pd.isna(detail["teu"]) else int(detail["teu"])
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
        st.markdown("**After the berth**")
        if not detail["container_likely"]:
            st.caption("Only estimated for likely container ships.")
        elif detail["Flag"] in (ARRIVED, IN_ANOTHER_PORT):
            st.caption("Already moored in Hamburg, or still in another port, so there is no berthing time to "
                       "plan from.")
        elif detail_teu is None:
            st.caption("The ship's length isn't known yet (it arrives with the next data collection), so unloading "
                       "can't be estimated.")
        else:
            plan = after_berth(detail["calc_eta_utc"], detail_teu, warehouse_km)

            def between(earliest, latest) -> str:
                return f"{nice_time(earliest)} to {nice_time(latest)}"

            def window(step: str) -> str:
                return between(*plan[step])

            fast_h, slow_h = plan["unloading_hours"]
            moves_low, moves_high = plan["moves"]
            st.markdown(md(
                f"About {detail_teu:,} TEU (estimated from its {detail['size_basis']}). If it berths at the "
                f"calculated ETA, about {plan['cranes']:.0f} cranes on average unload its roughly {moves_low:,} to "
                f"{moves_high:,} Hamburg containers in {max(fast_h, 1):.0f} to {max(slow_h, 1):.0f} hours."))
            st.markdown(md(f"First containers available for pickup: {window('first_ready')}.") + "  \n" +
                        md(f"All unloaded containers available: {window('all_ready')}.") + "  \n" +
                        md(f"By rail: on a train from {window('on_a_train')}.") + "  \n" +
                        md(f"By truck to a warehouse {warehouse_km} km away: from "
                           f"{between(plan['at_warehouse_first'][0], plan['at_warehouse_all'][1])}."))
            if isinstance(detail["cost"], dict):
                cost = detail["cost"]
                st.markdown(md(f"Running about {cost['days'] * 24:.0f} h late costs roughly "
                               f"{money_range(*cost['total'])} ({money_range(*cost['ship'])} ship time, "
                               f"{money_range(*cost['cargo'])} tied-up cargo). Ship rate from: {cost['rate_basis']}."))
            speed = usable_speed(detail["Speed (kn)"])
            distance = detail["Distance (nm)"]
            into_eu = voyage_emissions(detail_teu, speed, distance, config.ETS_SHARE_FROM_OUTSIDE_EU)
            within_eu = voyage_emissions(detail_teu, speed, distance, config.ETS_SHARE_BETWEEN_EU_PORTS)
            co2_low, co2_high = into_eu["co2_t"]
            st.markdown(md(f"The rest of its trip ({distance:,} nm at {speed:.0f} kn) emits about {co2_low:,.0f} to "
                           f"{co2_high:,.0f} t of CO2. EU ETS cost: {money_range(*into_eu['ets_usd'])} if it comes "
                           f"from outside the EU (50 % counted), {money_range(*within_eu['ets_usd'])} if it comes from "
                           f"an EU port (100 %)."))
            slower = slower_by(detail_teu, speed, distance, 2, config.ETS_SHARE_FROM_OUTSIDE_EU)
            if slower and distance > 50:
                st.markdown(md(f"Slow steaming, 2 knots slower, would save about {slower['share_saved']:.0%} of that "
                               f"fuel and CO2 ({money_range(*slower['money_saved_usd'])}), arriving "
                               f"{slower['hours_later']:.0f} h later."))
            st.caption("Estimates from the assumptions under How it works, with customs cleared before arrival. "
                       "If containers stay at the terminal beyond the free days, demurrage starts; if empty "
                       "containers come back late, detention starts. Both depend on your contract, not on this "
                       "ship being late.")
        st.caption(f"The crew typed the destination as {md(detail['Destination typed'])}. "
                   f"Speed used: {md(detail['Speed used'])}. Last position {md(detail['Position age (h)'])} h ago. "
                   f"MMSI {md(detail['MMSI'])}.")

# ---------------------------------------------------------------------------
# Shipping lines: which ones keep their promises (a procurement view)
# ---------------------------------------------------------------------------
with tab_lines:
    arrivals, arrivals_updated = load_arrivals()
    if not arrivals:
        st.subheader("No arrivals recorded yet")
        st.markdown("The scorecard fills up as the collector sees ships at sea and later moored in Hamburg.")
    else:
        score_rows = scorecard(arrivals)            # first row: all ships together, then one row per line
        all_ships = score_rows[0]
        known_lines = sum(1 for a in arrivals if a["line"] != UNKNOWN_LINE)
        st.subheader(md(f"{all_ships['On time']} of {all_ships['Judged']} cargo ships berthed within a day of the "
                        f"ETA they first reported to us"))
        st.markdown(md(
            f"Built from {len(arrivals)} real arrivals of cargo ships we saw at sea and later saw moored in "
            f"Hamburg. {known_lines} of them have a known shipping line so far; the rest are grouped as "
            f"{UNKNOWN_LINE}. A ship counts as on time if it berthed within {config.ON_TIME_TOLERANCE_HOURS} hours "
            f"of its promise, either way. A buyer of sea freight would use this to choose shipping lines and "
            f"negotiate with them."))
        too_few_label = f"needs {config.MIN_ARRIVALS_FOR_SCORE}+ judged arrivals"
        for row in score_rows:          # turn the share into text before the table is built (empty -> too_few_label)
            share = row["Schedule reliability"]
            row["Schedule reliability"] = f"{share:.0%}" if share is not None else too_few_label
        score_table = pd.DataFrame(score_rows)
        st.dataframe(score_table, hide_index=True, width="stretch", column_config={
            "Average delay (h)": st.column_config.NumberColumn(
                format="%+.1f", help="Middle of the berthing window minus the promised ETA. Negative = early."),
            "Unclear": st.column_config.NumberColumn(
                help="We look every ~3 hours, so we only know a window for each berthing. If that window "
                     "crosses the on-time limit, or no ETA was reported, the arrival is not judged."),
            "Judged": st.column_config.NumberColumn(help="Arrivals that are clearly on time, late or early."),
        })
        st.caption(md(
            "Why this looks better than industry reliability figures: the promise here is the ETA a ship "
            "reported the first time we saw it, usually a day or two before arrival in European waters. Industry "
            "figures (for example Sea-Intelligence) compare against the schedule published weeks earlier, so they "
            "are much lower. Compare shipping lines with each other here, not with those reports. "
            f"Ships whose name doesn't reveal the line are grouped as {UNKNOWN_LINE}."
            + (f" Updated {arrivals_updated:%d %b %Y, %H:%M} UTC." if arrivals_updated else "")))
        with st.expander("Every recorded arrival"):
            st.dataframe(pd.DataFrame([{
                "Ship": a["ship"], "Shipping line": a["line"], "Verdict": judge(a),
                "Promised ETA": nice_time(parse_time(a["promised_eta"])),
                "Berthed between": f"{nice_time(parse_time(a['arrived_after']))} and "
                                   f"{nice_time(parse_time(a['arrived_by']))}",
            } for a in reversed(arrivals)]), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Routes from Asia: Suez Canal or Cape of Good Hope (network design + CO2)
# ---------------------------------------------------------------------------
with tab_routes:
    asia = load_asia_routes()
    if not asia:
        st.subheader("No route table yet")
        st.markdown("Run `python tools/build_route_table.py` to build data/asia_routes.json.")
    else:
        pick_col, size_col, speed_col = st.columns([2, 1, 1])
        with pick_col:
            origin = st.selectbox("From", list(asia), index=list(asia).index("Shanghai") if "Shanghai" in asia else 0,
                                  format_func=lambda port: f"{port} ({asia[port]['region']})")
        with size_col:
            route_teu = st.slider("Ship size (TEU)", 1000, 24000, config.ROUTE_DEFAULT_TEU, step=500)
        with speed_col:
            route_speed = st.slider("Speed (knots)", 12, 22, config.ROUTE_DEFAULT_SPEED_KN)

        port_row = asia[origin]                     # this port's distances via Suez and via the Cape
        comparison = compare_routes(route_teu, route_speed, port_row["suez_nm"], port_row["cape_nm"])
        suez, cape, detour = comparison["Suez Canal"], comparison["Cape of Good Hope"], comparison["cape_detour"]

        st.subheader(md(f"From {origin}, the Cape detour adds {comparison['extra_nm']:,} nm and "
                        f"{comparison['extra_days']:.1f} days at {route_speed} knots"))
        st.markdown(md(
            f"For a {route_teu:,} TEU ship the Cape route is {detour['cape_is']} per voyage once fuel, EU ETS cost, "
            f"ship time and the Suez toll are counted (difference {money_range(*detour['total_usd'])}). It emits "
            f"{range_text(*detour['co2_t'])} t more CO2, which adds "
            f"{money_range(*detour['ets_usd'])} of EU ETS cost."))
        if red_sea_closed:
            st.info(md(f"Red Sea closed: every voyage from {origin} must take the Cape, "
                       f"{comparison['extra_days']:.1f} days longer each way. A weekly service needs "
                       f"{comparison['extra_ships_weekly']} more ship(s) to keep one departure a week."),
                    icon=":material/route:")

        def tonnes(pair) -> str:
            return f"{range_text(*pair)} t"

        rows_shown = [
            ("Distance", f"{suez['distance_nm']:,} nm", f"{cape['distance_nm']:,} nm", f"{comparison['extra_nm']:,} nm"),
            ("Days at sea", f"{suez['days']:.1f}", f"{cape['days']:.1f}", f"{comparison['extra_days']:.1f}"),
            ("Fuel", tonnes(suez["fuel_t"]), tonnes(cape["fuel_t"]), ""),
            ("CO2", tonnes(suez["co2_t"]), tonnes(cape["co2_t"]), tonnes(detour["co2_t"])),
            ("EU ETS cost (50 %)", money_range(*suez["ets_usd"]), money_range(*cape["ets_usd"]),
             money_range(*detour["ets_usd"])),
            ("Fuel cost", money_range(*suez["fuel_usd"]), money_range(*cape["fuel_usd"]), ""),
            ("Ship time (charter)", money_range(*suez["charter_usd"]), money_range(*cape["charter_usd"]), ""),
            ("Suez toll", money_range(*suez["toll_usd"]) + " (rough estimate)", "none", ""),
            ("Total", money_range(*suez["total_usd"]), money_range(*cape["total_usd"]),
             money_range(*detour["total_usd"])),
        ]
        if red_sea_closed:            # no Suez route: show only what ships must now do
            rows_shown = [(name, "closed", cape_value, extra) for name, _suez, cape_value, extra in rows_shown]
        st.dataframe(pd.DataFrame(rows_shown, columns=["", "Suez Canal", "Cape of Good Hope", "Cape detour adds"]),
                     hide_index=True, width="stretch")

        st.markdown("**Slow steaming around the Cape**")
        cape_slower = slower_by(route_teu, route_speed, port_row["cape_nm"], 2, config.ETS_SHARE_FROM_OUTSIDE_EU)
        if cape_slower:
            st.markdown(md(f"Sailing 2 knots slower ({route_speed - 2} instead of {route_speed}) saves about "
                           f"{cape_slower['share_saved']:.0%} of the fuel and CO2 ({tonnes(cape_slower['co2_saved_t'])} "
                           f"of CO2, {money_range(*cape_slower['money_saved_usd'])}) but arrives "
                           f"{cape_slower['hours_later'] / 24:.1f} days later."))

        st.markdown("**Every Asian port, at this ship size and speed**")
        all_ports = []
        for port, row in asia.items():
            port_comparison = compare_routes(route_teu, route_speed, row["suez_nm"], row["cape_nm"])
            all_ports.append({
                "From": port, "Region": row["region"],
                "Via Suez (nm)": "closed" if red_sea_closed else f"{row['suez_nm']:,}",
                "Via the Cape (nm)": f"{row['cape_nm']:,}",
                "Cape detour (nm)": port_comparison["extra_nm"],
                "Extra days": round(port_comparison["extra_days"], 1),
                "Extra CO2 (t)": range_text(*port_comparison["cape_detour"]["co2_t"]),
                "Extra ships, weekly service": port_comparison["extra_ships_weekly"],
            })
        st.dataframe(pd.DataFrame(all_ports).sort_values("Extra days", ascending=False), hide_index=True,
                     width="stretch", column_config={"Cape detour (nm)": st.column_config.NumberColumn(format="%d")})
        st.caption(
            "Distances from searoute (Eurostat's shipping-lane network) with the Suez and Panama canals blocked for "
            "the Cape route, checked against published Shanghai to Rotterdam figures (both routes within 0.4 % before "
            "a tiny calibration). Fuel from a ~13,000 TEU ship burning ~109 t a day at 18 knots, scaled by size and "
            "the cube of speed; CO2 = 3.151 t per t of fuel (IMO); EU ETS cost at 50 % for voyages into the EU, "
            "EUR 60-90 a tonne; fuel $670-730 a tonne (Rotterdam, Sept-Oct 2026). The Suez toll is a rough estimate: "
            "no official per-size table could be verified. South Asia and the Gulf lose the most from a Red Sea "
            "closure because they sit right next to it.")

# ---------------------------------------------------------------------------
# News and disruptions, plus the hand-written chokepoint notes
# ---------------------------------------------------------------------------
with tab_news:
    st.subheader("Disruptions in the news")
    st.caption(f"Headlines from the last {MAX_AGE_DAYS} days about storms, strikes, closures, congestion, accidents "
               "and conflict on the way to Hamburg. They come from maritime news sites and Google News, matched "
               "by keyword (no AI), and refresh every 3 hours. Select a headline to read the full article.")
    groups = [("near", "Near Hamburg, can delay ships arriving in the next days"),
              ("route", "Further along the route")]
    for where, heading in groups:
        st.markdown(f"**{heading}**")
        group = [headline for headline in headlines if headline["where"] == where]
        if not group:
            st.caption("Nothing reported.")
        for headline in group:
            st.markdown(headline_markdown(headline))
            st.caption(f"{md(headline['source'])}, {md(news_date(headline['published']))}")
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
    for zone in zones["zones"]:
        with st.expander(f"{md(zone['name'])}: {md(zone['status'])}",
                         icon=LEVEL_STYLE.get(zone["level"], ":material/help:")):
            st.markdown(md(zone["effect"]))
            link = safe_link(zone.get("source"))      # only plain https:// links are shown
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
7. **News**, shown under "What could hold ships up" and in full in the News and disruptions tab: headlines
   from maritime news sites and Google News (English and German).
   A headline is kept only if it names a place on the way to Hamburg **and** a disruption (storm, strike,
   closure, congestion, accident, attack), from the last 7 days. Plain keyword matching, no AI, so nothing is
   invented.
8. **Shipping lines** (procurement view): from the saved history we rebuild every cargo ship we saw at sea and
   later saw moored in Hamburg, and check it against the ETA it first reported. We only look every ~3 hours, so each
   berthing is a time window; a ship is judged on time or late only when the whole window agrees.
9. **After the berth**: ship size (TEU) from its length (never from its draught, which changes with the load); the
   share unloaded in Hamburg, the average number of cranes and their speed give an unloading time; then yard
   release, and either a train or the truck trip to your warehouse. Every step is a range from fastest to slowest.
10. **Cost of delay**: the ship's time (charter rate per day) plus the capital tied up in the delayed cargo.
11. **Routes from Asia**: for 25 Asian ports, the sea distance to Hamburg via the Suez Canal and around the Cape
    of Good Hope, and what the detour costs in days, fuel, CO2, EU ETS, ship time and Suez toll.
12. **CO2**: fuel from ship size and speed (fuel per day grows with the cube of speed), CO2 from fuel, and the
    EU ETS cost: 50 % of emissions for voyages into the EU, 100 % between EU ports.
""")
        st.subheader("Assumptions behind the estimates")
        share_low, share_high = config.UNLOAD_SHARE_RANGE
        rate_low, rate_high = config.CARGO_CAPITAL_RATE
        # Static wording with our own config numbers: no outside data, so no md() (it would escape the bullets).
        smallest, biggest = config.TEU_BY_LENGTH_M[0], config.TEU_BY_LENGTH_M[-1]
        fewest_cranes, most_cranes = config.CRANE_INTENSITY_BY_TEU[0], config.CRANE_INTENSITY_BY_TEU[-1]
        slow_cap, fast_cap = config.MAX_MOVES_PER_SHIP_PER_DAY
        sourced = ", ".join(f"{teu:,} TEU ${rate:,}" for teu, rate in config.SHIP_RATE_SOURCED)
        estimated = ", ".join(f"{teu:,} TEU ${rate:,}" for teu, rate in config.SHIP_RATE_ESTIMATED)
        narrow, wide = config.SHIP_RATE_SPREAD_BY_TEU
        # Static wording with our own config numbers: no outside data, so no md() (it would escape the bullets).
        st.markdown(f"""
- Ship size from length: a rule of thumb from typical container-ship classes, from {smallest[0]} m ≈ {smallest[1]:,} TEU to {biggest[0]} m ≈ {biggest[1]:,} TEU.
- Unloaded in Hamburg: {share_low:.0%} to {share_high:.0%} of the ship's capacity (assumption), {config.TEU_PER_MOVE} TEU per crane move.
- Cranes: on average {fewest_cranes[1]} for a {fewest_cranes[0]:,} TEU ship rising to {most_cranes[1]} for {most_cranes[0]:,} TEU, each moving {config.CRANE_MOVES_PER_HOUR[0]} to {config.CRANE_MOVES_PER_HOUR[1]} boxes an hour (top terminals reach about 40; no HHLA figure is published). One ship gets at most {slow_cap:,} (slow case, assumption) to {fast_cap:,} (Dynamar) moves a day.
- Unloading starts {config.START_UNLOADING_AFTER_BERTH_H[0]} to {config.START_UNLOADING_AFTER_BERTH_H[1]} h after berthing; containers are available for pickup {config.READY_FOR_PICKUP_AFTER_UNLOAD_H[0]} to {config.READY_FOR_PICKUP_AFTER_UNLOAD_H[1]} h after unloading; a train within {config.RAIL_WAIT_FOR_TRAIN_H[0]} to {config.RAIL_WAIT_FOR_TRAIN_H[1]} h; trucks at {config.TRUCK_SPEED_KMH[0]} to {config.TRUCK_SPEED_KMH[1]} km/h plus {config.TERMINAL_GATE_H[0]} to {config.TERMINAL_GATE_H[1]} h at the gate (assumptions).
- Ship time, sourced (New ConTex charter index, Aug to Oct 2026): {sourced} a day. Estimated beyond the index: {estimated} a day. Shown as plus or minus {narrow[1]:.0%} up to {narrow[0]:,} TEU, widening smoothly to {wide[1]:.0%} at {wide[0]:,} TEU and above.
- Cargo: ${config.CARGO_VALUE_PER_TEU_USD:,} per TEU (Sea-Intelligence benchmark) at {rate_low:.0%} to {rate_high:.0%} a year.
- Fuel: about {config.FUEL_REFERENCE['tonnes_per_day'][0]} to {config.FUEL_REFERENCE['tonnes_per_day'][1]} t a day for a {config.FUEL_REFERENCE['teu']:,} TEU ship at {config.FUEL_REFERENCE['speed_kn']} knots (sourced low end, +35 % for less efficient ships), scaled by size^(2/3) and speed^3; ${config.FUEL_PRICE_PER_TONNE_USD[0]} to ${config.FUEL_PRICE_PER_TONNE_USD[1]} a tonne (Rotterdam, Sept-Oct 2026).
- CO2: {config.CO2_PER_TONNE_FUEL} t per t of fuel (IMO). EU ETS: EUR {config.ETS_PRICE_PER_TONNE_EUR[0]} to {config.ETS_PRICE_PER_TONNE_EUR[1]} a tonne, {config.ETS_SHARE_FROM_OUTSIDE_EU:.0%} of emissions into the EU, {config.ETS_SHARE_BETWEEN_EU_PORTS:.0%} between EU ports; EUR 1 = ${config.EUR_TO_USD} (assumption).
- Suez toll: ${config.SUEZ_TOLL_PER_TEU_USD[0]} to ${config.SUEZ_TOLL_PER_TEU_USD[1]} per TEU of ship capacity, a rough estimate (the only figure found is unofficial; the 15 % rebate was withdrawn in April 2026).
""")
        st.subheader("Experimental ML estimate")
        if model:
            a, b, c = model["coefficients"]
            # The model file is written by a bot (see eta_model.load_model), so its values go through md() too.
            st.markdown(
                f"A straight-line model learned from **{md(model['ships'])} ships** ({md(model['examples'])} "
                f"examples) that we saw at sea and later saw moored in Hamburg, across {md(model['snapshots'])} "
                f"data snapshots:  \nreal hours ≈ {a:.2f} × calculated hours "
                f"+ {b:.1f} if the ship is not moving (waiting or in another port) + {c:.1f}")
            accuracy = md(ml_accuracy(model))
            if not ml_is_better(model):
                accuracy = f"**{accuracy}**"          # stand out when the plain calculation is the better one
            st.markdown(f"Tested fairly: each ship is predicted by a model that never saw it.  \n{accuracy}")
            trained = f"{model['trained_utc']:%d %b %Y, %H:%M} UTC" if model["trained_utc"] else "unknown"
            st.caption(f"Retrained automatically after each data collection. Last trained {md(trained)}. "
                       "Arrival times are only known to within ~3 hours (the gap between snapshots), and only "
                       "ships seen at sea and later moored in Hamburg while we were collecting count, so long trips are "
                       "under-represented.")
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
- **Shipping-line scores** need many arrivals. Most lines have only a few so far, so their percentage is hidden
  until there are enough. The "promise" is the crew's ETA when we first saw the ship, not the published schedule.
- **Unloading times and costs are estimates** built from published averages and stated assumptions. Real
  unloading depends on the terminal, the stowage plan and the weather; real costs depend on contracts we
  can't see.
- **Route and CO2 figures are estimates.** Real ships don't sail the shortest line, burn fuel according to their
  own engines and weather, and pay tolls from tables we couldn't verify. They are good for comparing routes,
  not for a ship's actual bill.
""")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(f"Built by Mohammad Zahid Abbas, M.Sc. student in International Logistics and Transportation "
           f"Management at UE Hamburg. Ship data from [AISStream.io](https://aisstream.io). "
           f"[Source code on GitHub]({REPO_URL}).")
