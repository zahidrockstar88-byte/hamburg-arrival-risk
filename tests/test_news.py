"""
Checks for news.py. No internet needed: we feed it made-up RSS text.
Run with:  python -m pytest
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from news import classify, clean_title, parse_feed  # noqa: E402

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

FEED = b"""<?xml version="1.0"?>
<rss><channel>
  <item><title>Collision blocks traffic in the Kiel Canal</title><link>https://example.com/kiel</link>
        <pubDate>Wed, 11 Nov 2026 08:00:00 +0000</pubDate></item>
  <item><title>Tanker attacked near Hormuz</title><link>javascript:alert(1)</link>
        <pubDate>Wed, 11 Nov 2026 08:00:00 +0000</pubDate></item>
  <item><title>Port of Hamburg reports record year</title><link>https://example.com/record</link>
        <pubDate>Wed, 11 Nov 2026 08:00:00 +0000</pubDate></item>
  <item><title>&lt;b&gt;Storm&lt;/b&gt; closes Elbe &amp; Hamburg terminals</title><link>https://example.com/storm</link>
        <pubDate>Tue, 10 Nov 2026 20:00:00 +0000</pubDate></item>
  <item><title>Old storm on the Elbe</title><link>https://example.com/old</link>
        <pubDate>Mon, 26 Oct 2026 08:00:00 +0000</pubDate></item>
  <item><title>Warnstreik im Hamburger Hafen - NDR.de</title><source>NDR.de</source>
        <link>https://news.google.com/rss/articles/abc?oc=5</link>
        <pubDate>Wed, 11 Nov 2026 06:00:00 +0000</pubDate></item>
  <item><title>Kreuzfahrt: Mein Schiff aendert Route - Hamburger Abendblatt</title>
        <source>Hamburger Abendblatt</source><link>https://news.google.com/rss/articles/def</link>
        <pubDate>Wed, 11 Nov 2026 06:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_feed_keeps_only_recent_safe_disruptions():
    items = {i["title"]: i for i in parse_feed(FEED, "Test", NOW)}
    assert items["Collision blocks traffic in the Kiel Canal"]["kind"] == "Accident"
    assert items["Collision blocks traffic in the Kiel Canal"]["where"] == "near"
    assert not any("Hormuz" in t for t in items)              # dropped: the link is not https
    assert not any("record year" in t for t in items)         # a place, but no disruption
    assert not any("Old storm" in t for t in items)           # older than 7 days
    storm = items["Storm closes Elbe & Hamburg terminals"]    # tags removed, &amp; decoded
    assert storm["kind"] == "Weather" and storm["place"] == "Port of Hamburg"


def test_google_news_publisher_is_split_off():
    items = {i["title"]: i for i in parse_feed(FEED, "Google News (DE)", NOW)}
    strike = items["Warnstreik im Hamburger Hafen"]
    assert strike["source"] == "NDR.de" and strike["kind"] == "Strike"
    # "Hamburger Abendblatt" is only the publisher's name, and cruises are off-topic: not kept.
    assert not any("Kreuzfahrt" in t for t in items)


def test_classify_rules():
    assert classify("Houthi missile attack in the Red Sea")["kind"] == "Conflict / security"
    assert classify("Evergreen resumes Suez transits")["kind"] == "Route update"      # conflict zone: always kept
    assert classify("Tanker strike near Hormuz as attacks mount")["kind"] == "Conflict / security"
    assert classify("Dense fog delays ships on the Elbe")["kind"] == "Weather"
    assert classify("Rotterdam port congestion worsens")["place"] == "North European ports"
    assert classify("Dockworkers strike at Port of Hamburg")["kind"] == "Strike"
    assert classify("North Sea oil workers strike over pay") is None          # not a port strike
    assert classify("Fire on North Sea gas platform") is None                 # off-topic: platforms
    assert classify("Shelbe Holdings storm damage") is None                   # 'elbe' inside a word: no place
    assert classify("Storm in Bavaria") is None                               # not on the way to Hamburg


def test_bad_feeds_are_ignored():
    bomb = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>
<rss><channel><item><title>&lol2; Suez</title><link>https://example.com/x</link></item></channel></rss>"""
    assert parse_feed(bomb, "Evil", NOW) == []
    assert parse_feed(b"<rss><channel><item>", "Broken", NOW) == []
    assert parse_feed(b"", "Empty", NOW) == []


def test_clean_title():
    assert clean_title("A\x00B\n  C") == "A B C"
    assert len(clean_title("x" * 500)) == 200
    assert clean_title(None) == ""


def test_city_news_is_not_a_shipping_disruption():
    # Examples from the code review: they name Hamburg or the Elbe but are not about ships.
    for headline in ["Hamburg Airport strike cancels 200 flights", "Bus drivers strike in Hamburg",
                     "Elbe flood hits Dresden old town", "Ice hockey: Hamburg Freezers win",
                     "Red Sea coral reef study published"]:
        assert classify(headline) is None, headline
    # Real disruptions are still kept.
    assert classify("Houthi missile attack in the Red Sea") is not None          # attack in a conflict zone
    assert classify("Warnstreik im Hamburger Hafen")["kind"] == "Strike"          # maritime place word
    assert classify("Head-on collision of two cargo ships blocks the Kiel Canal")["place"] == "Kiel Canal"


def test_airline_pilots_are_not_port_pilots_and_sea_storms_count():
    # Code review: an airline strike got through, and a plain North Sea storm warning was dropped.
    assert classify("Lufthansa pilots strike in Hamburg") is None
    assert classify("Elbe pilots strike halts Hamburg port traffic")["kind"] == "Strike"
    assert classify("North Sea storm warning")["kind"] == "Weather"
    assert classify("Gale warning for the English Channel")["place"] == "English Channel"
    assert classify("Elbe flood hits Dresden old town") is None          # still not about ships
