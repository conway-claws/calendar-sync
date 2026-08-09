"""Parse and serialize iCalendar text.

Events are plain dicts:
  uid         str
  title       str
  start       datetime.date (all-day) or aware datetime.datetime (timed)
  end         same type as start, or None
  all_day     bool
  location    str
  description str
  label       str or None (one of config.LABELS once classified)
"""

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import CALNAME, TZID

LOCAL = ZoneInfo(TZID)

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/Chicago
BEGIN:DAYLIGHT
DTSTART:19700308T020000
TZOFFSETFROM:-0600
TZOFFSETTO:-0500
RRULE:FREQ=YEARLY;BYDAY=2SU;BYMONTH=3
TZNAME:CDT
END:DAYLIGHT
BEGIN:STANDARD
DTSTART:19701101T020000
TZOFFSETFROM:-0500
TZOFFSETTO:-0600
RRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11
TZNAME:CST
END:STANDARD
END:VTIMEZONE"""


# --- parsing ---

def _unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text)


def _prop(block, name):
    """Return (params, value) for the first NAME line in block, or (None, None)."""
    m = re.search(
        r"(?:^|\n)" + name + r"((?:;[^:\n]*)?):([^\n]*)", block
    )
    if not m:
        return None, None
    return m.group(1), m.group(2).strip()


def _unescape(value):
    out = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt in ",;\\":
                out.append(nxt)
            elif nxt in "nN":
                out.append("\n")
            else:
                out.append(nxt)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_dt(params, value):
    """Return a date (all-day) or an America/Chicago-aware datetime."""
    if len(value) == 8:  # YYYYMMDD, VALUE=DATE
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    naive = datetime(
        int(value[0:4]), int(value[4:6]), int(value[6:8]),
        int(value[9:11]), int(value[11:13]), int(value[13:15]),
    )
    if value.endswith("Z"):
        return naive.replace(tzinfo=timezone.utc).astimezone(LOCAL)
    # TZID param or floating: the district publishes Chicago-local times
    return naive.replace(tzinfo=LOCAL)


def parse_ics(text):
    events = []
    skipped = 0
    for block in _unfold(text).split("BEGIN:VEVENT")[1:]:
        block = block.split("END:VEVENT")[0]
        _, uid = _prop(block, "UID")
        _, summary = _prop(block, "SUMMARY")
        sp, sval = _prop(block, "DTSTART")
        if not summary or not sval:
            continue
        ep, eval_ = _prop(block, "DTEND")
        _, location = _prop(block, "LOCATION")
        _, description = _prop(block, "DESCRIPTION")
        _, categories = _prop(block, "CATEGORIES")
        try:
            start = _parse_dt(sp, sval)
            end = _parse_dt(ep, eval_) if eval_ else None
        except ValueError:
            # One malformed event must not kill the nightly build; the
            # district's feed has served malformed items before.
            skipped += 1
            continue
        events.append({
            "uid": uid or "",
            "title": _unescape(summary),
            "start": start,
            "end": end,
            "all_day": isinstance(start, date) and not isinstance(start, datetime),
            "location": _unescape(location or ""),
            "description": _unescape(description or ""),
            "label": _unescape(categories).strip() or None if categories else None,
        })
    if skipped:
        import sys
        print(f"parse_ics: skipped {skipped} malformed event(s)", file=sys.stderr)
    return events


# --- serialization ---

def _escape(value):
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line):
    """Fold at 74 octets so lines stay within the RFC 5545 75-octet limit."""
    raw = line.encode("utf-8")
    if len(raw) <= 74:
        return line
    parts = []
    while raw:
        cut = min(74, len(raw))
        # never cut mid-codepoint: back up while the next byte is a continuation
        while 0 < cut < len(raw) and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        parts.append(raw[:cut].decode("utf-8"))
        raw = raw[cut:]
    return "\r\n ".join(parts)


def _fmt_dt(value):
    if isinstance(value, datetime):
        return f";TZID={TZID}:" + value.astimezone(LOCAL).strftime("%Y%m%dT%H%M%S")
    return ";VALUE=DATE:" + value.strftime("%Y%m%d")


def _sort_key(ev):
    s = ev["start"]
    if isinstance(s, datetime):
        s = s.date()
    return (s.isoformat(), ev["uid"])


def serialize(events, calname=CALNAME):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//conway-claws//calendar-sync//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calname)}",
        f"X-WR-TIMEZONE:{TZID}",
    ]
    lines.extend(VTIMEZONE.splitlines())
    for ev in sorted(events, key=_sort_key):
        start = ev["start"]
        end = ev["end"]
        if end is None:
            if isinstance(start, datetime):
                end = start + timedelta(hours=1)
            else:
                end = start + timedelta(days=1)  # DTEND is exclusive for dates
        # DTSTAMP is required by RFC 5545; derive it from the event's start date
        # instead of build time so rebuilds with unchanged content diff clean.
        stamp_day = start.date() if isinstance(start, datetime) else start
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev['uid']}")
        lines.append("DTSTAMP:" + stamp_day.strftime("%Y%m%d") + "T000000Z")
        lines.append("DTSTART" + _fmt_dt(start))
        lines.append("DTEND" + _fmt_dt(end))
        lines.append(f"SUMMARY:{_escape(ev['title'])}")
        if ev.get("label"):
            lines.append(f"CATEGORIES:{ev['label']}")
        if ev.get("location"):
            lines.append(f"LOCATION:{_escape(ev['location'])}")
        if ev.get("description"):
            lines.append(f"DESCRIPTION:{_escape(ev['description'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
