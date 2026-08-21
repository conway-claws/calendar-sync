"""Shared configuration for calendar-sync."""

ORG_ID = 17714  # Conway High School on the district's Apptegy instance
LIVE_FEED_SECTION_ID = 294859

ICAL_URL = (
    "https://thrillshare-cmsv2.services.thrillshare.com"
    f"/api/v4/o/{ORG_ID}/cms/events/generate_ical?filter_ids&section_ids"
)
FEED_URL = (
    "https://api.thrillshare.com"
    f"/api/v4/o/{ORG_ID}/cms/live_feeds"
    f"?section_ids={LIVE_FEED_SECTION_ID}&page_no=1&per_page=25"
)
# CHS athletics composite schedule (Mascot Media DigitalSuite).
ATHLETICS_ICS_URL = (
    "https://mmboltapi.azurewebsites.net/api/v2/events/calendar/2482279/0/calendar.ics"
)

# The Conway Orchestras program calendar (Google Calendar); this is the
# public iCal address conwayorchestras.weebly.com/calendar.html publishes.
ORCHESTRA_ICS_URL = (
    "https://calendar.google.com/calendar/ical"
    "/conwayorchestras%40gmail.com/public/basic.ics"
)

# Direct-iCal sources: (source name, URL, label fallback for events whose
# CATEGORIES is missing or not a CLAWS label). Priority lives in build.PRIORITY.
ICS_SOURCES = (
    ("ical", ICAL_URL, None),
    ("athletics", ATHLETICS_ICS_URL, "ATHLETICS"),
    ("orchestra", ORCHESTRA_ICS_URL, "ARTS"),
)

# CLAWS covers Conway High School, grades 10-12; both program feeds carry
# more. The athletics composite lists every secondary school's teams and the
# orchestra calendar spans the whole 6-12 program, so an iCal event whose
# title names a feeder-school team or grade is dropped. (The text-source
# extractor already enforces this boundary in its prompt.) MS is matched
# case-sensitively so a "Ms. Smith" title never trips it.
NON_CHS_TITLE = (
    r"\bMS\b"
    r"|(?i:\bmiddle schools?\b|\bjunior high\b|\bcjhs\b|\b[5-9]th grade\b)"
)

# Per-source drops beyond the CHS boundary. The orchestra calendar mirrors
# district calendar dates under its own titles ("First Day of School!",
# "End 1st Quarter"); the district feed is canonical for those. A retitled
# mirror dodges the fuzzy dedup and doubles up, and a close-enough one
# outranks and replaces the district's title, so both are dropped here.
ICS_EXCLUDE = {
    "orchestra": (
        r"(?i)\bopen house\b|\b(?:first|last) day of school\b|\bno school\b"
        r"|\bteacher work ?day\b|\blabor day\b|\b(?:fall|spring|winter) break\b"
        r"|\bquarters?\b|\bsemesters?\b|\bparent[- ]teacher\b"
    ),
}

# CLAWS-curated RSS roundup of CHS-adjacent feeds (sports, boosters).
RSS_URL = "https://rss.app/feeds/_AeJmcGomMid09LzK.xml"

# The CHS morning announcements Doc, exported as plain text (link-shared).
DOC_ID = "1K0tvF2RzP2OpdSyqiv2PR2IntSX0oO0-SBVSmR5jkng"
DOC_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"

# The CHS Announcements newsletter on the district's edurooms site (Apptegy).
# The page server-renders the latest issue's email HTML into its Nuxt data
# payload, so the anonymous page fetch is enough; the engage API behind it
# requires auth.
NEWSLETTER_URL = (
    "https://conwaypublicschools.edurooms.com"
    "/newsletters/conway-high-school/newsletters/chs-announcements"
)

UA = "conway-claws-calendar-sync/0.1 (+https://github.com/conway-claws/calendar-sync)"
TZID = "America/Chicago"

WINDOW_DAYS = 90        # how far ahead the calendar is built
REMOVAL_CAP = 15        # more removals than this in one run aborts the build
MAX_EVENTS_PER_EXTRACT = 50  # cap on LLM-extracted events per source (untrusted input)

LABELS = ("ATHLETICS", "ARTS", "ACADEMICS", "ACTIVITIES")
DEFAULT_LABEL = "ACTIVITIES"

CALNAME = "Conway CLAWS"
UID_DOMAIN = "calendar-sync.conwaypto.org"
