import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import build
import classify
import extract
import ical

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LOCAL = ZoneInfo("America/Chicago")


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.events = ical.parse_ics((FIXTURES / "ical.ics").read_text())

    def test_counts_and_titles(self):
        self.assertEqual(len(self.events), 3)
        self.assertEqual(
            [e["title"] for e in self.events],
            ["Professional Development - No Students", "School Board Meeting",
             "Volleyball vs Cabot"],
        )

    def test_all_day_range(self):
        pd = self.events[0]
        self.assertTrue(pd["all_day"])
        self.assertEqual(pd["start"], date(2026, 8, 10))
        self.assertEqual(pd["end"], date(2026, 8, 14))

    def test_folded_and_escaped_props(self):
        board = self.events[1]
        self.assertIn("conwayschools", board["description"])  # folded line rejoined
        self.assertEqual(board["location"], "2220 Prince St, Conway, AR 72034, USA")

    def test_utc_converted_to_chicago(self):
        vb = self.events[2]
        self.assertEqual(vb["start"], datetime(2026, 8, 12, 18, 0, tzinfo=LOCAL))
        self.assertFalse(vb["all_day"])


class RoundTripTests(unittest.TestCase):
    def test_parse_serialize_parse(self):
        first = ical.parse_ics((FIXTURES / "ical.ics").read_text())
        for e in first:
            e["label"] = "ACTIVITIES"
        second = ical.parse_ics(ical.serialize(first))
        self.assertEqual(len(first), len(second))
        for a, b in zip(sorted(first, key=build.event_day),
                        sorted(second, key=build.event_day)):
            for key in ("title", "location", "description", "all_day", "label"):
                self.assertEqual(a[key], b[key], key)
            self.assertEqual(build.event_day(a), build.event_day(b))

    def test_serialize_is_deterministic(self):
        events = ical.parse_ics((FIXTURES / "ical.ics").read_text())
        self.assertEqual(ical.serialize(events), ical.serialize(list(reversed(events))))

    def test_long_lines_fold(self):
        ev = {"uid": "x@y", "title": "T" * 200, "start": date(2026, 9, 1),
              "end": None, "all_day": True, "location": "", "description": "",
              "label": None}
        for line in ical.serialize([ev]).split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)

    def test_folding_never_splits_multibyte(self):
        # non-breaking spaces and accents, as the district's descriptions carry
        ev = {"uid": "x@y", "title": "Fiesta", "start": date(2026, 9, 1),
              "end": None, "all_day": True, "location": "",
              "description": ("Escuela Secundaria Conway " + "cafetería " * 30).strip(),
              "label": None}
        text = ical.serialize([ev])  # raises UnicodeDecodeError if misfolded
        back = ical.parse_ics(text)
        self.assertEqual(back[0]["description"], ev["description"])


class ClassifyTests(unittest.TestCase):
    CASES = {
        "Volleyball vs Cabot": "ATHLETICS",
        "Homecoming Game": "ATHLETICS",
        "Dance Team Tryouts": "ATHLETICS",
        "Marching Band Competition": "ARTS",
        "Choir Concert": "ARTS",
        "Professional Development - No Students": "ACADEMICS",
        "Fall Break - No School": "ACADEMICS",
        "Parent/Teacher Conferences": "ACADEMICS",
        "Deadline: Yearbook photo": "ACADEMICS",
        "PTO General Meeting": "ACTIVITIES",
        "Spirit Night at Larry's Pizza": "ACTIVITIES",
        "Homecoming Dance": "ACTIVITIES",
        "School Board Meeting": "ACTIVITIES",
    }

    def test_rules(self):
        for title, want in self.CASES.items():
            self.assertEqual(classify.label_for(title), want, title)

    def test_llm_fallback_only_when_no_rule_matches(self):
        self.assertEqual(classify.label_for("Something Unusual", "ARTS"), "ARTS")
        self.assertEqual(classify.label_for("Something Unusual", "bogus"), "ACTIVITIES")
        self.assertEqual(classify.label_for("Choir Concert", "ATHLETICS"), "ARTS")


class ExtractPayloadTests(unittest.TestCase):
    def test_validation_and_deadline_prefix(self):
        payload = {"events": [
            {"title": "PTO general meeting", "date": "2026-08-18",
             "start_time": "18:30", "end_time": None, "location": "CHS library",
             "description": "", "label": "ACTIVITIES", "is_deadline": False},
            {"title": "Yearbook photo", "date": "2026-09-04", "start_time": "08:00",
             "end_time": None, "location": None, "description": "",
             "label": "ACADEMICS", "is_deadline": True},
            {"title": "Stale", "date": "2026-01-01", "start_time": None,
             "end_time": None, "location": None, "description": "",
             "label": "ACTIVITIES", "is_deadline": False},
            {"title": "Bad date", "date": "not-a-date", "start_time": None,
             "end_time": None, "location": None, "description": "",
             "label": "ACTIVITIES", "is_deadline": False},
        ]}
        events = extract.events_from_payload(payload, "doc", today=date(2026, 8, 9))
        self.assertEqual(len(events), 2)
        meeting, deadline = events
        self.assertEqual(meeting["start"],
                         datetime(2026, 8, 18, 18, 30, tzinfo=LOCAL))
        self.assertEqual(deadline["title"], "Deadline: Yearbook photo")
        self.assertTrue(deadline["all_day"])  # deadlines drop their times

    def test_event_cap(self):
        payload = {"events": [
            {"title": f"E{i}", "date": "2026-08-20", "start_time": None,
             "end_time": None, "location": None, "description": "",
             "label": "ACTIVITIES", "is_deadline": False}
            for i in range(200)
        ]}
        events = extract.events_from_payload(payload, "feed", today=date(2026, 8, 9))
        self.assertEqual(len(events), extract.MAX_EVENTS_PER_EXTRACT)


class RssParseTests(unittest.TestCase):
    def test_items_become_stripped_blobs(self):
        import sources
        posts = sources.parse_rss((FIXTURES / "rss.xml").read_text())
        self.assertEqual(len(posts), 2)
        self.assertIn("Beaverfork Park", posts[0])
        self.assertNotIn("<div>", posts[0])  # HTML stripped
        self.assertIsNone(sources.parse_rss("not xml at all"))


class DedupTests(unittest.TestCase):
    def _ev(self, title, source, day=date(2026, 8, 10)):
        return {"uid": "u" if source == "ical" else "", "title": title,
                "start": day, "end": None, "all_day": True, "location": "",
                "description": "", "label": None, "source": source}

    def test_ical_wins_over_feed(self):
        kept = build.dedup([
            self._ev("Meet the Cats Volleyball Showcase", "feed"),
            self._ev("Meet the Cats/Volleyball Showcase", "ical"),
        ])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["source"], "ical")

    def test_program_feed_wins_over_district(self):
        kept = build.dedup([
            self._ev("Volleyball vs Cabot", "ical"),
            self._ev("Girls Varsity Volleyball vs Cabot", "athletics"),
        ])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["source"], "athletics")

    def test_same_source_similar_titles_survive(self):
        kept = build.dedup([
            self._ev("Volleyball vs Cabot", "ical"),
            self._ev("JV Volleyball vs Cabot", "ical"),
        ])
        self.assertEqual(len(kept), 2)

    def test_malformed_event_skipped_not_fatal(self):
        import ical
        text = (FIXTURES / "ical.ics").read_text().replace(
            "DTSTART:20260811T180000", "DTSTART:garbage")
        events = ical.parse_ics(text)
        self.assertEqual(len(events), 2)  # the bad event dropped, rest survive

    def test_distinct_events_survive(self):
        kept = build.dedup([
            self._ev("Volleyball vs Cabot", "ical"),
            self._ev("PTO General Meeting", "doc"),
        ])
        self.assertEqual(len(kept), 2)

    def test_uid_stability(self):
        a = build.assign_uid(self._ev("PTO General Meeting", "doc"))
        b = build.assign_uid(self._ev("PTO General Meeting", "doc"))
        self.assertEqual(a["uid"], b["uid"])
        self.assertTrue(a["uid"].startswith("doc-"))
        # already-final uids (carried forward) are left alone
        self.assertEqual(build.assign_uid(dict(a))["uid"], a["uid"])


class OrchestraParseTests(unittest.TestCase):
    def setUp(self):
        self.events = ical.parse_ics((FIXTURES / "orchestra.ics").read_text())

    def test_valarm_props_do_not_leak_into_event(self):
        concert = self.events[0]
        self.assertEqual(concert["title"], "Fall Concert")
        self.assertEqual(concert["description"], "")  # alarm's DESCRIPTION dropped
        self.assertEqual(concert["uid"], "11111111-1111-1111-1111-111111111111")

    def test_rrule_and_exdate_captured(self):
        self.assertEqual(self.events[1]["rrule"],
                         "FREQ=YEARLY;INTERVAL=1;BYDAY=-1SA;BYMONTH=8")
        self.assertEqual(self.events[2]["exdates"], {date(2012, 12, 10)})


class ExpandRecurrenceTests(unittest.TestCase):
    def setUp(self):
        self.events = ical.parse_ics((FIXTURES / "orchestra.ics").read_text())

    def test_yearly_byday_projects_into_window(self):
        out = ical.expand_recurrences(self.events, date(2026, 8, 9), date(2026, 11, 8))
        titles = [e["title"] for e in out]
        self.assertIn("Fall Concert", titles)  # non-recurring passes through
        self.assertNotIn("After-School Rehearsal", titles)  # rule ended in 2012
        porch = [e for e in out if e["title"] == "Play Music on the Porch Day"]
        self.assertEqual([e["start"] for e in porch], [date(2026, 8, 29)])
        self.assertIsNone(porch[0]["rrule"])  # occurrences carry no rule

    def test_weekly_until_and_exdate(self):
        out = ical.expand_recurrences(self.events, date(2012, 12, 1), date(2012, 12, 31))
        rehearsals = sorted(
            (e for e in out if e["title"] == "After-School Rehearsal"),
            key=lambda e: e["start"],
        )
        self.assertEqual([e["start"].date() for e in rehearsals],
                         [date(2012, 12, 3), date(2012, 12, 17)])  # 12-10 EXDATEd
        first = rehearsals[0]
        self.assertEqual(first["start"].hour, 16)  # local wall time preserved
        self.assertEqual(first["end"] - first["start"], timedelta(minutes=90))

    def test_recurrence_id_override_replaces_occurrence(self):
        out = ical.expand_recurrences(self.events, date(2026, 8, 9), date(2026, 11, 8))
        sales = [e for e in out if e["title"] == "Ad Sales begin"]
        # the moved 2026 occurrence appears once, on its new date only
        self.assertEqual([e["start"] for e in sales], [date(2026, 8, 31)])

    def test_unsupported_rule_keeps_base_occurrence(self):
        ev = dict(self.events[1], rrule="FREQ=MONTHLY;BYDAY=2TU")
        out = ical.expand_recurrences([ev], date(2026, 8, 9), date(2026, 11, 8))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["start"], date(2020, 8, 29))


class IcsSourceTests(unittest.TestCase):
    TODAY = date(2026, 8, 10)

    def test_athletics_events_carry_hint_label(self):
        text = (FIXTURES / "athletics.ics").read_text()
        evs = build.ics_events("athletics", text, "ATHLETICS", self.TODAY)
        self.assertEqual(len(evs), 3)
        self.assertTrue(all(e["source"] == "athletics" for e in evs))
        self.assertTrue(all(e["label"] == "ATHLETICS" for e in evs))

    def test_orchestra_window_and_hint(self):
        text = (FIXTURES / "orchestra.ics").read_text()
        evs = build.ics_events("orchestra", text, "ARTS", self.TODAY)
        self.assertEqual({e["title"] for e in evs},
                         {"Fall Concert", "Play Music on the Porch Day",
                          "Ad Sales begin"})
        # the hint survives final classification when no labels.tsv rule matches
        porch = next(e for e in evs if e["title"] == "Play Music on the Porch Day")
        self.assertEqual(classify.label_for(porch["title"], porch["label"]), "ARTS")


if __name__ == "__main__":
    unittest.main()
