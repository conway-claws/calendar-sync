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
  rrule       str or None (raw RRULE value; expand_recurrences consumes it)
  exdates     set of date (RRULE occurrences to skip)
  recurrence_id  date or None (this event overrides that occurrence of its UID)
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
        # Drop VALARM sub-blocks first: their UID/DESCRIPTION lines would
        # otherwise satisfy the first-match property lookups below.
        block = re.sub(r"BEGIN:VALARM.*?END:VALARM", "", block, flags=re.S)
        _, uid = _prop(block, "UID")
        _, summary = _prop(block, "SUMMARY")
        sp, sval = _prop(block, "DTSTART")
        if not summary or not sval:
            continue
        ep, eval_ = _prop(block, "DTEND")
        _, location = _prop(block, "LOCATION")
        _, description = _prop(block, "DESCRIPTION")
        _, categories = _prop(block, "CATEGORIES")
        _, rrule = _prop(block, "RRULE")
        _, rec_id = _prop(block, "RECURRENCE-ID")
        recurrence_id = None
        if rec_id and len(rec_id) >= 8 and rec_id[:8].isdigit():
            recurrence_id = date(int(rec_id[0:4]), int(rec_id[4:6]), int(rec_id[6:8]))
        exdates = set()
        for m in re.finditer(r"(?:^|\n)EXDATE[^:\n]*:([^\n]*)", block):
            for v in m.group(1).split(","):
                v = v.strip()
                if len(v) >= 8 and v[:8].isdigit():
                    exdates.add(date(int(v[0:4]), int(v[4:6]), int(v[6:8])))
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
            "rrule": rrule,
            "exdates": exdates,
            "recurrence_id": recurrence_id,
        })
    if skipped:
        import sys
        print(f"parse_ics: skipped {skipped} malformed event(s)", file=sys.stderr)
    return events


# --- recurrence expansion ---

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _nth_weekday(year, month, token):
    """Resolve a yearly BYDAY token like '2SU' or '-1SA' within a month."""
    m = re.fullmatch(r"(-?\d+)([A-Z]{2})", token)
    if not m or m.group(2) not in WEEKDAYS:
        return None
    n, wd = int(m.group(1)), WEEKDAYS[m.group(2)]
    if n > 0:
        d = date(year, month, 1)
        d += timedelta((wd - d.weekday()) % 7 + (n - 1) * 7)
    else:
        d = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1))
        d -= timedelta(days=1)
        d -= timedelta((d.weekday() - wd) % 7 + (-n - 1) * 7)
    return d if d.month == month else None


def _rule_days(rule, start_day):
    """Yield occurrence days for the RRULE shapes real feeds use, in order.

    Handles DAILY/WEEKLY/YEARLY with INTERVAL, COUNT, UNTIL, BYDAY, BYMONTH.
    Returns None for anything else so the caller can fall back to the base
    occurrence instead of guessing.
    """
    parts = {}
    for p in rule.split(";"):
        if "=" in p:
            k, v = p.split("=", 1)
            parts[k] = v
    freq = parts.get("FREQ")
    if freq not in ("DAILY", "WEEKLY", "YEARLY"):
        return None
    try:
        interval = int(parts.get("INTERVAL", 1))
        count = int(parts["COUNT"]) if "COUNT" in parts else None
        until = None
        if "UNTIL" in parts:
            u = parts["UNTIL"]
            until = date(int(u[0:4]), int(u[4:6]), int(u[6:8]))
    except ValueError:
        return None
    month = byday = None
    if freq == "YEARLY":
        try:
            month = int(parts["BYMONTH"]) if "BYMONTH" in parts else start_day.month
        except ValueError:
            return None
        byday = parts.get("BYDAY")
        if not 1 <= month <= 12:
            return None
        if byday and _nth_weekday(2024, month, byday) is None:
            return None  # unparseable token would otherwise never terminate

    def days():
        if freq == "DAILY":
            day = start_day
            while True:
                yield day
                day += timedelta(days=interval)
        elif freq == "WEEKLY":
            bydays = sorted(
                WEEKDAYS[t] for t in parts.get("BYDAY", "").split(",")
                if t in WEEKDAYS
            ) or [start_day.weekday()]
            week = start_day - timedelta(days=start_day.weekday())
            while True:
                for wd in bydays:
                    day = week + timedelta(days=wd)
                    if day >= start_day:
                        yield day
                week += timedelta(days=7 * interval)
        else:  # YEARLY
            year = start_day.year
            while True:
                if byday:
                    day = _nth_weekday(year, month, byday)
                else:
                    try:
                        day = date(year, month, start_day.day)
                    except ValueError:  # Feb 29 in a non-leap year
                        day = None
                if day is not None and day >= start_day:
                    yield day
                year += interval

    def bounded():
        for i, day in enumerate(days()):
            if count is not None and i >= count:
                return
            if until is not None and day > until:
                return
            yield day

    return bounded()


def expand_recurrences(events, first_day, last_day):
    """Replace each recurring event with its occurrences in [first_day, last_day].

    An event whose rule can't be interpreted keeps its base occurrence only,
    with a note on stderr; a wrong guess would invent events on the calendar.
    An event carrying a RECURRENCE-ID replaces that occurrence of its UID's
    rule (a moved rehearsal, say) and passes through as its own event.
    """
    overridden = {
        (ev["uid"], ev["recurrence_id"])
        for ev in events if ev.get("recurrence_id") and ev["uid"]
    }
    out = []
    for ev in events:
        rule = ev.get("rrule")
        if not rule:
            out.append(ev)
            continue
        base_day = ev["start"].date() if isinstance(ev["start"], datetime) else ev["start"]
        occurrences = _rule_days(rule, base_day)
        if occurrences is None:
            import sys
            print(f"expand_recurrences: unsupported rule kept as one event: "
                  f"{rule!r} ({ev['title']})", file=sys.stderr)
            out.append(dict(ev, rrule=None))
            continue
        duration = ev["end"] - ev["start"] if ev["end"] is not None else None
        for day in occurrences:
            if day > last_day:
                break
            if day < first_day or day in ev.get("exdates", ()):
                continue
            if (ev["uid"], day) in overridden:
                continue
            if isinstance(ev["start"], datetime):
                start = ev["start"].replace(year=day.year, month=day.month, day=day.day)
            else:
                start = day
            out.append(dict(
                ev, rrule=None, exdates=set(), start=start,
                end=start + duration if duration is not None else None,
            ))
    return out


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
