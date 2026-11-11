"""
Checks for safety.py: untrusted text must never turn into links, images or formatting.
Run with:  python -m pytest
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from safety import clean_ais_text, md, safe_link, to_float, to_int  # noqa: E402


def test_clean_ais_text():
    assert clean_ais_text("  msc   sindy@@@@ ") == "MSC SINDY"
    assert clean_ais_text("ÄÖÜ ship\t\n") == "SHIP"
    assert len(clean_ais_text("A" * 500)) == 20
    assert len(clean_ais_text("ABCDEFGHIJ", "callsign")) == 7
    assert clean_ais_text(None) == "" and clean_ais_text(12345) == ""


def test_numbers():
    assert to_int("71", 0, 99) == 71
    assert to_int(150, 0, 99) is None
    assert to_int("abc") is None and to_int(True) is None and to_int(None) is None
    assert to_float("12.5", 0, 102.3) == 12.5
    assert to_float(float("nan")) is None and to_float("inf", 0, 100) is None


def test_markdown_is_escaped():
    # A ship could call itself a Markdown link or image. After md() it must be plain text.
    assert "](" not in md("[CLICK](HTTP://X.CO)")
    assert md("[CLICK](HTTP://X.CO)").startswith("\\[")
    assert md("![](HTTP://X.CO/A.PNG)").startswith("\\!\\[")
    assert "\\:" in md("HTTP://X.CO")          # stops automatic links
    assert md(None) == ""


def test_only_https_links_are_allowed():
    assert safe_link("https://maritime-executive.com/article/x-y") == "https://maritime-executive.com/article/x-y"
    assert safe_link("javascript:alert(1)") is None
    assert safe_link("http://example.com") is None
    assert safe_link("https://example.com/a)(evil") is None
    assert safe_link("") is None and safe_link(None) is None


def test_ais_not_available_codes_are_rejected():
    from safety import COURSE_RANGE, SPEED_RANGE, clean_eta
    assert to_float(102.3, *SPEED_RANGE) is None and to_float(14.5, *SPEED_RANGE) == 14.5
    assert to_float(360, *COURSE_RANGE) is None and to_float(270, *COURSE_RANGE) == 270
    assert clean_eta({"Month": 13, "Day": 32, "Hour": 25, "Minute": 61}) == {"Month": 0, "Day": 0, "Hour": 0, "Minute": 0}
    assert clean_eta({"Month": 11, "Day": 2, "Hour": 6, "Minute": 30}) == {"Month": 11, "Day": 2, "Hour": 6, "Minute": 30}
    assert clean_eta("not a dict") is None
