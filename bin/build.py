#!/usr/bin/env python3
"""Build docs/claws.ics (and one sub-feed per label) from the sources.

Usage:
  python3 bin/build.py                # fetch live sources, write docs/
  python3 bin/build.py --dry-run      # plan only, write nothing
  python3 bin/build.py --force        # override the removal cap
  python3 bin/build.py --offline DIR  # read <source>.ics/feed.json/doc.txt from DIR

Exit codes: 0 built (or clean dry run), 2 aborted on the removal cap.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

import classify
import extract
import ical
import sources
from config import (
    CALNAME, ICS_EXCLUDE, ICS_SOURCES, LABELS, NON_CHS_TITLE, REMOVAL_CAP,
    UID_DOMAIN, WINDOW_DAYS,
)

NON_CHS_RE = re.compile(NON_CHS_TITLE)
EXCLUDE_RES = {name: re.compile(pattern) for name, pattern in ICS_EXCLUDE.items()}

DOCS = Path(__file__).resolve().parent.parent / "docs"
# Program-run calendars outrank the district's generic feed for their own
# events: the programs maintain fuller titles, times, and locations.
PRIORITY = {"athletics": 5, "orchestra": 4, "ical": 3, "doc": 2, "feed": 1, "rss": 0}


def event_day(ev):
    s = ev["start"]
    return s.date() if isinstance(s, datetime) else s


def in_window(ev, today):
    return today - timedelta(days=1) <= event_day(ev) <= today + timedelta(days=WINDOW_DAYS)


def similar(a, b):
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def assign_uid(ev):
    if ev["uid"].endswith(f"@{UID_DOMAIN}"):
        return ev  # carried forward from the previous build, already final
    # Identity is content-derived for every source: the district's iCal
    # endpoint mints fresh random UIDs on each request, so its UIDs are noise.
    key = f"{ev['title']}|{event_day(ev).isoformat()}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    ev["uid"] = f"{ev['source']}-{digest}@{UID_DOMAIN}"
    return ev


def dedup(events):
    """Collapse cross-source duplicates; higher-priority source wins.

    Fuzzy matching applies only across sources: within one source, same-day
    similar titles (JV and Varsity games, say) are distinct real events.
    """
    events = sorted(events, key=lambda e: -PRIORITY[e["source"]])
    kept = []
    for ev in events:
        dupe = any(
            k["source"] != ev["source"]
            and event_day(k) == event_day(ev)
            and similar(k["title"], ev["title"]) >= 0.6
            for k in kept
        )
        if not dupe:
            kept.append(ev)
    return kept


def ics_events(name, text, label_hint, today):
    """Window-filtered events of one direct-iCal source, recurrences expanded."""
    evs = ical.expand_recurrences(
        ical.parse_ics(text),
        today - timedelta(days=1), today + timedelta(days=WINDOW_DAYS),
    )
    extra = EXCLUDE_RES.get(name)
    evs = [
        e for e in evs
        if in_window(e, today)
        and not NON_CHS_RE.search(e["title"])
        and not (extra and extra.search(e["title"]))
    ]
    for e in evs:
        e["source"] = name
        if e["label"] not in LABELS:
            e["label"] = label_hint
    return evs


def gather(offline_dir, today):
    """Return ({source: events or None}, notes). None = fetch failed."""
    notes = []
    per_source = {}

    if offline_dir:
        d = Path(offline_dir)
        ics_texts = {
            name: (d / f"{name}.ics").read_text() if (d / f"{name}.ics").exists() else None
            for name, _, _ in ICS_SOURCES
        }
        feed_posts = None
        if (d / "feed.json").exists():
            feed_posts = ["Post: " + p for p in json.loads((d / "feed.json").read_text())]
        rss_posts = (
            sources.parse_rss((d / "rss.xml").read_text())
            if (d / "rss.xml").exists() else None
        )
        doc_text = (d / "doc.txt").read_text() if (d / "doc.txt").exists() else None
    else:
        ics_texts = {
            name: sources.fetch_ical(url) if url else ""
            for name, url, _ in ICS_SOURCES
        }
        feed_posts = sources.fetch_feed_posts()
        rss_posts = sources.fetch_rss_posts()
        doc_text = sources.fetch_doc()

    for name, _, label_hint in ICS_SOURCES:
        text = ics_texts[name]
        if text == "":  # no URL configured (and no offline file): source is off
            per_source[name] = []
            notes.append(f"{name}: no URL configured, source disabled")
            continue
        if text is None:
            per_source[name] = None
            notes.append(f"{name}: fetch FAILED, carrying previous events forward")
            continue
        per_source[name] = ics_events(name, text, label_hint, today)

    text_sources = (
        ("doc", doc_text),
        ("feed", "\n---\n".join(feed_posts or []) or None),
        ("rss", "\n---\n".join(rss_posts or []) or None),
    )
    for name, text in text_sources:
        if text is None:
            per_source[name] = None
            notes.append(f"{name}: fetch FAILED, carrying previous events forward")
            continue
        if not text.strip():
            per_source[name] = []
            continue
        evs = extract.extract(text, name, today)
        if evs is None:
            per_source[name] = None
            notes.append(f"{name}: extraction unavailable, carrying previous events forward")
        else:
            per_source[name] = [e for e in evs if in_window(e, today)]

    return per_source, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--offline", metavar="DIR")
    args = ap.parse_args()

    today = date.today()
    master_path = DOCS / "claws.ics"
    old_events = ical.parse_ics(master_path.read_text()) if master_path.exists() else []
    old_by_uid = {e["uid"]: e for e in old_events}

    per_source, notes = gather(args.offline, today)

    new_events = []
    for name, evs in per_source.items():
        if evs is None:
            # Failed source: keep its previous events so a flaky fetch can't
            # mass-delete. Staleness self-heals when the source comes back.
            new_events.extend(
                e | {"source": name} for e in old_events
                if e["uid"].startswith(f"{name}-") and in_window(e, today)
            )
        else:
            new_events.extend(evs)

    for ev in new_events:
        ev["label"] = classify.label_for(ev["title"], ev.get("label"))
    new_events = [assign_uid(e) for e in dedup(new_events)]

    new_by_uid = {e["uid"]: e for e in new_events}
    added = sorted(set(new_by_uid) - set(old_by_uid))
    removed = sorted(set(old_by_uid) - set(new_by_uid))
    changed = sorted(
        u for u in set(new_by_uid) & set(old_by_uid)
        if ical.serialize([new_by_uid[u]]) != ical.serialize([old_by_uid[u]])
    )

    print(f"plan: {len(new_events)} events | +{len(added)} added, "
          f"-{len(removed)} removed, ~{len(changed)} changed")
    for note in notes:
        print(f"note: {note}")
    for uid in added:
        e = new_by_uid[uid]
        print(f"  + {event_day(e)} [{e['label']}] {e['title']}")
    for uid in removed:
        e = old_by_uid[uid]
        print(f"  - {event_day(e)} {e['title']}")

    if len(removed) > REMOVAL_CAP and not args.force:
        print(f"ABORT: {len(removed)} removals exceeds cap of {REMOVAL_CAP}; "
              "rerun with --force if intended", file=sys.stderr)
        return 2

    if args.dry_run:
        return 0

    DOCS.mkdir(exist_ok=True)
    master_path.write_text(ical.serialize(new_events))
    for label in LABELS:
        subset = [e for e in new_events if e["label"] == label]
        path = DOCS / f"claws-{label.lower()}.ics"
        path.write_text(ical.serialize(subset, f"{CALNAME} - {label.title()}"))
    print(f"wrote {master_path} and {len(LABELS)} label feeds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
