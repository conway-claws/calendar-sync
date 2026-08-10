# calendar-sync

**One labeled calendar for Conway High School events.**

A daily GitHub Action merges six public feeds into `docs/claws.ics` and one
sub-feed per label, served by GitHub Pages. Calendar apps subscribe to the
published URLs.

Maintained by [Conway CLAWS](https://conwaypto.org).

## How it works

```
CHS athletics schedule (iCal)   ──┐
Conway Orchestras cal (iCal)    ──┤
district event feed (iCal)      ──┼─► extract ─► label ─► dedup ─► docs/*.ics
district live feed (JSON)       ──┤   (Claude)   (rules)
CLAWS social roundup (RSS)      ──┤
CHS morning announcements       ──┘
```

1. **Sources.** Three feeds arrive as iCal and are parsed directly: the CHS
   athletics composite schedule (Mascot Media), the Conway Orchestras program
   calendar (Google Calendar), and the district's Thrillshare event feed.
   The CHS live feed, the CLAWS RSS roundup of CHS-adjacent feeds (sports,
   boosters), and the CHS morning announcements Doc are free text; Claude
   extracts dated events from them under a fixed JSON schema. All fetches are
   anonymous. Cross-source duplicates resolve in priority order: athletics
   schedule, orchestra calendar, district feed, Doc, live feed, RSS - a
   program's own calendar carries fuller titles, times, and locations than
   the district's generic entry for the same event, so it wins.
2. **Labels.** Every event carries one of **ATHLETICS**, **ARTS**,
   **ACADEMICS**, **ACTIVITIES**. Rules in `labels.tsv` decide first, the
   extractor's suggestion (or a per-feed fallback: ATHLETICS for the athletics
   schedule, ARTS for the orchestra calendar) is next, ACTIVITIES is the default. Each label
   also ships as its own sub-feed (`claws-athletics.ics`, …). The 4-way split is
   CLAWS-defined; the district publishes no event taxonomy.
3. **Build.** `bin/build.py` merges the sources, drops cross-source duplicates,
   assigns content-derived UIDs (`title|date` hash), and writes the feeds for a
   rolling 90-day window. Git history is the change log.

## Rules

1. The published ICS is the source of truth; subscribed calendars are read-only
   copies. Nothing here writes to any calendar account.
2. Live-feed, RSS, and Doc text is untrusted data: extraction runs under a
   fixed schema, a 50-event cap, and re-validation of every field.
3. A failed source carries its previous events forward. A build that would
   remove more than 15 events aborts and opens an issue.
4. Output is diff-stable: sorted events, content-derived DTSTAMPs and UIDs. A
   rebuild with unchanged sources is byte-identical.

## Running it

```
python3 test/test_calendar_sync.py            # offline test suite
python3 bin/build.py --dry-run                # plan against live sources
python3 bin/build.py                          # build docs/
python3 bin/build.py --offline test/fixtures  # fully offline build
```

Extraction reads `ANTHROPIC_API_KEY`; `CLAUDE_MODEL` overrides the model
(default `claude-opus-5`). Without a key the build runs on the district feed
alone.

## Runbook

- Schedule: `.github/workflows/sync.yml`, daily 12:00 UTC, commits as
  `github-actions[bot]`. Failures and aborted builds open an issue labeled
  `sync-failure`.
- Secret: `ANTHROPIC_API_KEY`, a repository Actions secret.
- Feeds: `https://calendar.conwaypto.org/claws.ics` and
  `claws-athletics.ics` / `claws-arts.ics` / `claws-academics.ics` /
  `claws-activities.ics`, served by GitHub Pages from `docs/` on `main`. In
  Google Calendar: *Add calendar → From URL*.
- The CHS morning announcements Doc is link-shared for anonymous export; its ID is in
  `bin/config.py`. `doc: fetch FAILED` in the build notes means the share or
  the ID changed.
- The district's Apptegy org and section IDs, the athletics schedule URL, and
  the orchestra calendar URL are in `bin/config.py`. An iCal source whose URL
  is set to None is disabled: the build notes `no URL configured` and runs
  without it.
