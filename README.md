# calendar-sync

**One labeled calendar for Conway High School events.**

A daily GitHub Action merges four public feeds into `docs/claws.ics` and one
sub-feed per label, served by GitHub Pages. Calendar apps subscribe to the
published URLs.

Maintained by [Conway CLAWS](https://conwaypto.org).

## How it works

```
district event feed (iCal)  ──┐
district live feed (JSON)   ──┼─► extract ─► label ─► dedup ─► docs/*.ics
CLAWS social roundup (RSS)  ──┤   (Claude)   (rules)
CLAWS announcements (Doc)   ──┘
```

1. **Sources.** The district's Thrillshare event feed is fetched as iCal and
   parsed directly. The CHS live feed, the CLAWS RSS roundup of CHS-adjacent
   feeds (sports, boosters), and the CLAWS announcements Doc are free text;
   Claude extracts dated events from them under a fixed JSON schema. All four
   fetches are anonymous. Cross-source duplicates resolve in priority order:
   district feed, Doc, live feed, RSS.
2. **Labels.** Every event carries one of **ATHLETICS**, **ARTS**,
   **ACADEMICS**, **COMMUNITY**. Rules in `labels.tsv` decide first, the
   extractor's suggestion is the fallback, COMMUNITY is the default. Each label
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

## Adding events

Board members type events into the CLAWS announcements Doc, plain sentences
with a date. The next build picks them up.

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
  `claws-community.ics`, served by GitHub Pages from `docs/` on `main`. In
  Google Calendar: *Add calendar → From URL*.
- The announcements Doc is link-shared for anonymous export; its ID is in
  `bin/config.py`. `doc: fetch FAILED` in the build notes means the share or
  the ID changed.
- The district's Apptegy org and section IDs are in `bin/config.py`.
