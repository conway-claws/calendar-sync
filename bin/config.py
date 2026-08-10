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

# CLAWS-curated RSS roundup of CHS-adjacent feeds (sports, boosters).
RSS_URL = "https://rss.app/feeds/_AeJmcGomMid09LzK.xml"

# The CHS morning announcements Doc, exported as plain text (link-shared).
DOC_ID = "1K0tvF2RzP2OpdSyqiv2PR2IntSX0oO0-SBVSmR5jkng"
DOC_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"

UA = "conway-claws-calendar-sync/0.1 (+https://github.com/conway-claws/calendar-sync)"
TZID = "America/Chicago"

WINDOW_DAYS = 90        # how far ahead the calendar is built
REMOVAL_CAP = 15        # more removals than this in one run aborts the build
MAX_EVENTS_PER_EXTRACT = 50  # cap on LLM-extracted events per source (untrusted input)

LABELS = ("ATHLETICS", "ARTS", "ACADEMICS", "ACTIVITIES")
DEFAULT_LABEL = "ACTIVITIES"

CALNAME = "Conway CLAWS"
UID_DOMAIN = "calendar-sync.conwaypto.org"
