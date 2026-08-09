"""Credential-less fetchers for the three sources.

Each returns raw material for the build; None means the fetch failed (as
distinct from succeeding with nothing in it), so the build can carry the
source's previous events forward instead of deleting them.
"""

import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

from config import DOC_URL, FEED_URL, ICAL_URL, RSS_URL, UA


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in (1, 2, 3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception:
            if attempt == 3:
                return None
            time.sleep(5 * attempt)


def fetch_ical():
    text = _get(ICAL_URL)
    if text is None or "BEGIN:VCALENDAR" not in text:
        return None
    return text


def fetch_feed_posts():
    """Recent live-feed posts as plain-text blobs for extraction."""
    text = _get(FEED_URL)
    if text is None:
        return None
    try:
        posts = json.loads(text).get("live_feeds", [])
    except ValueError:
        return None
    return ["Post: " + (p.get("status") or "") for p in posts if p.get("status")]


def parse_rss(text):
    """RSS items as plain-text blobs for extraction; HTML stripped for tokens."""
    try:
        channel = ET.fromstring(text).find("channel")
    except ET.ParseError:
        return None
    if channel is None:
        return None
    posts = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        desc = re.sub(r"\s+", " ", desc).strip()
        if title or desc:
            posts.append(f"Post: {title}\n{desc}".strip())
    return posts


def fetch_rss_posts():
    text = _get(RSS_URL)
    if text is None:
        return None
    return parse_rss(text)


def fetch_doc():
    text = _get(DOC_URL)
    if text is None or text.lstrip().startswith("<"):
        return None  # an HTML login/error page, not the doc export
    return text
