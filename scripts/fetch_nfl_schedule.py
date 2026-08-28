#!/usr/bin/env python3
"""Regenerate a season's cached NFL schedule file used for "primetime drama" commentary.

The naive single-call approach (`dates={season}&seasontype=2&limit=1000`, no `week` param)
does NOT reliably return the full season -- ESPN's scoreboard endpoint silently falls back to
a narrow default window (observed: only the season's first couple weeks) when `week` is
omitted. This loops week-by-week, which reliably returns each week's real games.

Usage:
    python3 scripts/fetch_nfl_schedule.py <seasonId>

Writes nfl-schedule-<seasonId>.json at the repo root as {"events": [...]}, merging every
regular-season week (1-18). Re-run this whenever a season's schedule needs refreshing (e.g.
once near the start of a new season, or if playoffs demand a shifted week 18 boundary).
"""
import json
import sys
import urllib.request

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
REGULAR_SEASON_WEEKS = range(1, 19)


def fetch_week(season, week):
    url = f"{BASE}?dates={season}&seasontype=2&week={week}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp).get("events", [])


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/fetch_nfl_schedule.py <seasonId>", file=sys.stderr)
        sys.exit(1)

    season = int(sys.argv[1])
    events_by_id = {}
    for week in REGULAR_SEASON_WEEKS:
        events = fetch_week(season, week)
        print(f"week {week}: {len(events)} events", file=sys.stderr)
        for e in events:
            events_by_id[e["id"]] = e

    out_path = f"nfl-schedule-{season}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"events": list(events_by_id.values())}, f, ensure_ascii=True)
    print(f"wrote {len(events_by_id)} events to {out_path}")


if __name__ == "__main__":
    main()
