"""
news.py - Recent news about disruptions that can delay ships on their way to Hamburg.

How it works:
  1. Download public RSS feeds (news lists): maritime news sites, plus Google News
     searches in English and German for the Port of Hamburg, the Elbe and nearby waters.
  2. Keep a headline only if it names a PLACE on the way to Hamburg (Hamburg, Elbe,
     Kiel Canal, North Sea, nearby ports, the Channel, Red Sea...) AND a DISRUPTION
     (storm, fog, strike, closure, congestion, collision, attack...) AND is about ships
     (a shipping word like "port", "vessel", "Hafen", or a maritime place like "HHLA").
     Attacks in conflict zones like the Red Sea or Hormuz, and storms at sea (North Sea,
     Channel), count without a shipping word.
  3. Keep only the last few days, newest first, grouped into "near Hamburg"
     (can delay ships arriving in the next days) and "further along the route".

No AI is used: plain keyword matching, so it can't make things up. It only shows
what news sites published, with a link to the original article.

Security: news feeds come from the internet, so we treat them as untrusted.
  - defusedxml reads the feed (it blocks XML tricks like "billion laughs").
  - Downloads have a time limit and a size limit.
  - Titles are cleaned to plain text; only https:// links are kept.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from safety import clean_plain_text, safe_link


def _google_news(query: str, language: str) -> str:
    """A Google News search as an RSS feed (free, no account). 'when:7d' = last 7 days."""
    region = {"en": "hl=en&gl=DE&ceid=DE:en", "de": "hl=de&gl=DE&ceid=DE:de"}[language]
    return f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(query + ' when:7d')}&{region}"


FEEDS = {
    "gCaptain": "https://gcaptain.com/feed/",
    "Splash247": "https://splash247.com/feed/",
    "The Loadstar": "https://theloadstar.com/feed/",
    "Hellenic Shipping News": "https://www.hellenicshippingnews.com/feed/",
    "Container News": "https://container-news.com/feed/",
    "Google News (EN)": _google_news(
        '("Port of Hamburg" OR "Hamburg port" OR Elbe OR "Kiel Canal" OR "German Bight" OR "North Sea") '
        '(strike OR storm OR fog OR closure OR closed OR congestion OR delay OR collision OR aground)', "en"),
    "Google News (DE)": _google_news(
        '("Hamburger Hafen" OR "Hafen Hamburg" OR Elbe OR "Nord-Ostsee-Kanal" OR Nordsee) '
        '(Streik OR Warnstreik OR Sturm OR Sturmflut OR Orkan OR Nebel OR Sperrung OR gesperrt OR Stau OR Havarie)',
        "de"),
}

# Places on the way to Hamburg. "near" = close enough to delay ships arriving in the next days.
PLACES = {
    "Port of Hamburg": ("near", ["hamburger hafen", "hafen hamburg", "port of hamburg", "hamburg port", "hhla",
                                 "eurogate", "altenwerder", "burchardkai", "hamburg", "elbe", "cuxhaven",
                                 "brunsbüttel", "brunsbuettel"]),
    "Kiel Canal": ("near", ["kiel canal", "nord-ostsee-kanal"]),
    "North Sea / German Bight": ("near", ["north sea", "german bight", "nordsee", "deutsche bucht"]),
    "North European ports": ("near", ["rotterdam", "antwerp", "antwerpen", "bremerhaven", "wilhelmshaven",
                                      "north europe", "northern europe", "nordrange", "north range"]),
    "English Channel": ("near", ["english channel", "dover strait", "strait of dover", "ärmelkanal"]),
    "Red Sea / Suez": ("route", ["red sea", "suez", "bab el-mandeb", "bab al-mandab", "houthi", "houthis",
                                 "rotes meer", "suezkanal"]),
    "Strait of Hormuz": ("route", ["hormuz", "persian gulf", "arabian gulf"]),
    "Gibraltar / Cape route": ("route", ["gibraltar", "cape of good hope", "cape route", "bay of biscay"]),
}
CONFLICT_PLACES = {"Red Sea / Suez", "Strait of Hormuz"}     # news there matters even without a disruption word
SEA_PLACES = {"North Sea / German Bight", "English Channel"}    # weather there always affects ships

# What kind of disruption a headline is about (English and German words).
DISRUPTIONS = {        # checked in this order: the first kind that matches wins
    "Conflict / security": ["attack", "attacks", "attacked", "missile", "drone", "seized", "hijacked",
                            "angriff", "angriffe", "beschuss"],
    "Accident": ["collision", "collide", "collides", "aground", "grounding", "grounded", "fire", "capsized",
                 "havarie", "kollision", "unfall", "brand", "auf grund"],
    "Weather": ["storm", "storms", "gale", "gales", "hurricane", "fog", "high winds", "storm surge", "flood",
                "low water", "ice", "sturm", "sturmflut", "orkan", "nebel", "hochwasser", "niedrigwasser", "eis"],
    "Closure": ["closure", "closed", "closes", "suspended", "suspends", "blocked", "blockage", "blocks", "shut",
                "sperrung", "gesperrt", "geschlossen", "blockiert"],
    "Strike": ["strike", "strikes", "walkout", "industrial action", "streik", "streiks", "warnstreik",
               "ver.di", "verdi", "arbeitsniederlegung"],
    "Congestion / delays": ["congestion", "congested", "delay", "delays", "delayed", "backlog", "waiting times",
                            "bottleneck", "stau", "verspätung", "verspätungen", "wartezeit", "wartezeiten"],
}

# Place words that are about shipping by themselves. Any other place ("Hamburg", "Elbe", "North Sea")
# also needs a shipping word, so city news like "bus drivers strike in Hamburg" is not kept.
MARITIME_PLACE_WORDS = ["hamburger hafen", "hafen hamburg", "port of hamburg", "hamburg port", "hhla", "eurogate",
                        "altenwerder", "burchardkai", "kiel canal", "nord-ostsee-kanal", "german bight",
                        "deutsche bucht", "dover strait", "strait of dover", "bab el-mandeb", "bab al-mandab",
                        "suez canal", "suezkanal", "strait of hormuz", "cape route"]

# Words that show a headline is about ships or ports.
SHIPPING_CONTEXT = ["port", "ports", "harbour", "harbor", "ship", "ships", "shipping", "vessel", "vessels",
                    "container", "containers", "cargo", "freighter", "tanker", "tankers", "carrier", "carriers",
                    "terminal", "terminals", "berth", "dock", "docks", "dockworkers", "dockers", "harbour pilots",
                    "harbor pilots", "maritime pilots", "river pilots", "elbe pilots", "lock", "locks", "canal",
                    "transit", "transits", "seafarers", "crew", "maritime", "navigation", "hafen", "häfen", "schiff",
                    "schiffe", "schifffahrt", "frachter", "frachtschiff", "reederei", "containerschiff", "lotsen",
                    "schleuse", "liegeplatz"]

# A strike only delays ships if it hits the port itself: docks, terminals, pilots, locks.
STRIKE_CONTEXT = ["port", "ports", "dock", "docks", "dockworkers", "dockers", "longshore", "terminal", "terminals",
                  "harbour pilots", "harbor pilots", "maritime pilots", "river pilots", "elbe pilots", "lock", "locks",
                  "hafen", "häfen", "hafenarbeiter", "lotsen", "schleuse"]

# Headlines with these words are about something else (oil platforms, cruises, sport...), not cargo ship delays.
OFF_TOPIC = ["platform", "oilfield", "oil field", "gas field", "rig", "offshore worker", "offshore workers",
             "cruise", "kreuzfahrt", "football", "bundesliga", "hsv", "st. pauli", "marathon", "concert",
             "airport", "flughafen", "flights", "flüge", "airline", "airlines", "lufthansa", "eurowings", "condor",
             "cockpit", "hockey", "eishockey", "coral", "reef",
             # research and science articles: about storms in general, not a storm hitting ships now
             "modeling", "modelling", "model", "models", "study", "studies", "research", "researchers",
             "scientists", "studie", "forscher",
             # beaches and tourism: storm news that doesn't affect ships
             "beach", "beaches", "tourists", "holiday", "strand", "urlaub", "touristen", "badegäste"]

USER_AGENT = "HamburgArrivalRiskMonitor/1.0 (+https://github.com/zahidrockstar88-byte/hamburg-arrival-risk)"
TIMEOUT_SECONDS = 10
MAX_FEED_BYTES = 2_000_000          # 2 MB is far more than any real news feed
MAX_TITLE_LENGTH = 200
MAX_AGE_DAYS = 7                    # older news is not about ships arriving now


def clean_title(raw) -> str:
    """Plain text only: remove HTML tags, decode '&amp;' etc., then the shared clean-up in safety.py."""
    if not isinstance(raw, str):
        return ""
    return clean_plain_text(html.unescape(re.sub(r"<[^>]*>", " ", raw)), MAX_TITLE_LENGTH)


def _mentions(text: str, words: list[str]) -> bool:
    """True if any word appears as a whole word ("elbe" counts, "Shelbe" does not)."""
    return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) for word in words)


def classify(title: str) -> dict | None:
    """
    Decide if a headline is a disruption on the way to Hamburg.
    Returns {"place", "where" ("near"/"route"), "kind"} or None.
    """
    lowered = title.lower()
    if _mentions(lowered, OFF_TOPIC):
        return None
    place = next((name for name, (_, words) in PLACES.items() if _mentions(lowered, words)), None)
    if place is None:
        return None
    kind = next((name for name, words in DISRUPTIONS.items() if _mentions(lowered, words)), None)
    if kind is None and place not in CONFLICT_PLACES:
        return None                                    # e.g. "Hamburg port reports record year": not a disruption
    conflict_news = place in CONFLICT_PLACES and kind == "Conflict / security"
    weather_at_sea = place in SEA_PLACES and kind == "Weather"      # e.g. "North Sea storm warning"
    about_shipping = _mentions(lowered, MARITIME_PLACE_WORDS) or _mentions(lowered, SHIPPING_CONTEXT)
    if not (conflict_news or weather_at_sea or about_shipping):
        return None                                    # e.g. "Elbe flood hits Dresden": not about ships
    if kind == "Strike" and not _mentions(lowered, STRIKE_CONTEXT):
        return None                                    # e.g. bus drivers or oil workers striking: ships still sail
    return {"place": place, "where": PLACES[place][0], "kind": kind or "Route update"}


def parse_feed(xml_bytes: bytes, source: str, now: datetime | None = None) -> list[dict]:
    """Read one RSS feed and return recent headlines about disruptions."""
    now = now or datetime.now(timezone.utc)
    try:
        root = ElementTree.fromstring(xml_bytes)
    except (ElementTree.ParseError, DefusedXmlException, ValueError):
        return []
    items = []
    for item in root.iter("item"):
        title = clean_title(item.findtext("title"))
        publisher = clean_title(item.findtext("source")) or source
        # Google News adds " - Publisher" to every title; remove it so the publisher's name isn't matched.
        if publisher != source and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()
        link = safe_link((item.findtext("link") or "").strip())
        match = classify(title)
        if not title or not link or not match:
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            published = None
        if published is None or not (now - timedelta(days=MAX_AGE_DAYS) <= published <= now + timedelta(hours=1)):
            continue                                   # undated, too old, or dated in the future
        items.append({"title": title, "link": link, "source": publisher, "published": published, **match})
    return items


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:   # only our fixed https:// feeds
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("feed too large")
    return data


def latest_headlines(limit: int = 30) -> tuple[list[dict], list[str]]:
    """
    Download every feed and return (headlines newest first, names of feeds that failed).
    A feed that is down never breaks the page; it is just listed as unavailable.
    """
    now = datetime.now(timezone.utc)
    headlines, failed = [], []
    for source, url in FEEDS.items():
        try:
            headlines += parse_feed(_download(url), source, now)
        except Exception:               # network error, timeout, bad feed: skip this one
            failed.append(source)
    seen, unique = set(), []
    for headline in sorted(headlines, key=lambda item: item["published"], reverse=True):
        key = re.sub(r"\W+", " ", headline["title"].lower()).strip()
        if key not in seen:                            # the same story can appear in two feeds
            seen.add(key)
            unique.append(headline)
    return unique[:limit], failed
