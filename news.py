"""
news.py - Recent news about disruptions that can delay ships on their way to Hamburg.

How it works:
  1. Download public RSS feeds (news lists): maritime news sites, plus Google News
     searches in English and German for the Port of Hamburg, the Elbe and nearby waters.
  2. Keep a headline only if it names a PLACE on the way to Hamburg (Hamburg, Elbe,
     Kiel Canal, North Sea, nearby ports, the Channel, Red Sea...) AND a DISRUPTION
     (storm, fog, strike, closure, congestion, collision, attack...).
     Conflict zones like the Red Sea or Hormuz count even without a disruption word.
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

from safety import safe_link


def _google_news(query: str, language: str) -> str:
    """A Google News search as an RSS feed (free, no account). 'when:3d' = last 3 days."""
    region = {"en": "hl=en&gl=DE&ceid=DE:en", "de": "hl=de&gl=DE&ceid=DE:de"}[language]
    return f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(query + ' when:3d')}&{region}"


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
    "Port of Hamburg": ("near", ["hamburg", "hamburger hafen", "hafen hamburg", "hhla", "eurogate", "elbe",
                                 "cuxhaven", "brunsbüttel", "brunsbuettel", "altenwerder", "burchardkai"]),
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

# A strike only delays ships if it hits the port itself: docks, terminals, pilots, locks.
STRIKE_CONTEXT = ["port", "ports", "dock", "docks", "dockworkers", "dockers", "longshore", "terminal", "terminals",
                  "pilot", "pilots", "lock", "locks", "hafen", "häfen", "hafenarbeiter", "lotsen", "schleuse",
                  "hamburg", "rotterdam", "antwerp", "bremerhaven"]

# Headlines with these words are about something else (oil platforms, cruises, sport...), not cargo ship delays.
OFF_TOPIC = ["platform", "oilfield", "oil field", "gas field", "rig", "offshore worker", "offshore workers",
             "cruise", "kreuzfahrt", "football", "bundesliga", "hsv", "st. pauli", "marathon", "concert"]

USER_AGENT = "HamburgArrivalRiskMonitor/1.0 (+https://github.com/zahidrockstar88-byte/hamburg-arrival-risk)"
TIMEOUT_SECONDS = 10
MAX_FEED_BYTES = 2_000_000          # 2 MB is far more than any real news feed
MAX_TITLE_LENGTH = 200
MAX_AGE_DAYS = 7                    # older news is not about ships arriving now


def clean_title(raw) -> str:
    """Plain text only: remove HTML tags, decode '&amp;' etc., single spaces, limited length."""
    if not isinstance(raw, str):
        return ""
    text = html.unescape(re.sub(r"<[^>]*>", " ", raw))
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)          # invisible control characters
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TITLE_LENGTH]


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
    if kind == "Strike" and not _mentions(lowered, STRIKE_CONTEXT):
        return None                                    # e.g. oil platform workers striking: ships still sail
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
        found = classify(title)
        if not title or not link or not found:
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            published = None
        if published is None or not (now - timedelta(days=MAX_AGE_DAYS) <= published <= now + timedelta(hours=1)):
            continue                                   # undated, too old, or dated in the future
        items.append({"title": title, "link": link, "source": publisher, "published": published, **found})
    return items


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:   # noqa: S310 (fixed https URLs)
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
    for h in sorted(headlines, key=lambda h: h["published"], reverse=True):
        key = re.sub(r"\W+", " ", h["title"].lower()).strip()
        if key not in seen:                            # the same story can appear in two feeds
            seen.add(key)
            unique.append(h)
    return unique[:limit], failed
