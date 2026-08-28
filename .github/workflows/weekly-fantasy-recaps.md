---
name: Weekly Fantasy Football Recaps
description: Fetch ESPN results and create reviewed weekly recaps for every configured league
on:
  schedule:
    - cron: "0 14 * * 2"
  workflow_dispatch:
permissions:
  contents: read
strict: true
model: gemini-2.5-flash
engine:
  id: gemini
imports:
  - .github/agents/fantasy-football.agent.md
max-ai-credits: 500
max-turns: 30
network:
  allowed:
    - defaults
    - github
    - lm-api-reads.fantasy.espn.com
    - generativelanguage.googleapis.com
tools:
  edit:
  repo-memory:
    branch-name: memory/fantasy-recaps
    allowed-extensions:
      - ".json"
    file-glob:
      - "history/*.json"
    max-file-size: 1048576
    max-file-count: 50
    max-patch-size: 1048576
  bash:
    - cat
    - date
    - ls
    - mkdir
    - find
mcp-scripts:
  fetch-espn-leagues:
    description: Fetch the current completed-week ESPN data for every league in config.json. Credentials are isolated to this read-only tool and are never returned.
    py: |
      import json
      import os
      from pathlib import Path
      from urllib.parse import urlencode
      from urllib.request import Request, urlopen

      root = Path.cwd()
      config = json.loads((root / "config.json").read_text(encoding="utf-8"))
      swid = os.environ.get("ESPN_SWID")
      espn_s2 = os.environ.get("ESPN_S2")
      if not swid or not espn_s2:
          raise RuntimeError("ESPN_SWID and ESPN_S2 must be configured as repository secrets")

      headers = {
          "Accept": "application/json",
          "Cookie": f"SWID={swid}; espn_s2={espn_s2}",
          "User-Agent": "FantasyFootballWeeklySummary/1.0",
      }
      base = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league}"
      views = "mMatchupScore,mTeam,mBoxscore,mTransactions2"

      def fetch(url):
          with urlopen(Request(url, headers=headers), timeout=60) as response:
              return json.load(response)

      results = {}
      for key, league in config.get("leagues", {}).items():
          params = {"view": views}
          metadata_url = base.format(season=league["seasonId"], league=league["leagueId"]) + "?" + urlencode(params)
          metadata = fetch(metadata_url)
          status = metadata.get("status", {})
          week = next((status.get(name) for name in ("previousScoringPeriod", "latestScoringPeriod", "currentMatchupPeriod") if isinstance(status.get(name), int) and status.get(name) > 0), None)
          if week is None:
              raise RuntimeError(f"ESPN did not provide a completed matchup period for {key}")
          params["scoringPeriodId"] = str(week)
          data_url = base.format(season=league["seasonId"], league=league["leagueId"]) + "?" + urlencode(params)
          results[key] = {"league": league, "week": week, "data": fetch(data_url)}

      print(json.dumps(results, ensure_ascii=True))
    env:
      ESPN_SWID: ${{ secrets.ESPN_SWID }}
      ESPN_S2: ${{ secrets.ESPN_S2 }}
safe-outputs:
  create-pull-request:
    title-prefix: "[recap] "
    draft: true
    max: 1
    if-no-changes: warn
    allowed-files:
      - "*/*/week-*/data.json"
      - "*/*/week-*/stats.json"
      - "*/*/week-*/players.json"
      - "*/*/week-*/recap.md"
    protected-files: blocked
    fallback-as-issue: false
---

# Weekly Fantasy Football Recaps

Run the `fetch-espn-leagues` tool once. It returns the current completed matchup data for every league in the root `config.json`; process every returned league, never just the first one. The tool keeps `ESPN_SWID` and `ESPN_S2` outside the agent and does not return them.

Use repo memory at `/tmp/gh-aw/repo-memory-default/history/` for long-term trend history. For each league and season, read and update `history/{league-key}-{seasonId}.json` with only verified week number, team score, winner/loser, and lowest-scorer results. This history branch is independent of the recap pull request and must be used when checking repeat lowest scorers or season trends. Never store credentials, cookies, raw API responses, owner personal data beyond what is needed for the trend, or generated prose in repo memory.

For each league:

1. Infer and use the week returned by the fetch tool. Do not ask the user for a week and do not use a hard-coded week.
2. Read the root `nfl-schedule.json` if present. Filter its raw `events[]` to the league season and returned week. In the cached ESPN shape, `event.season.type` is normally integer `2` for regular season, `event.week.number` is the week, and `event.id` is the game ID. Skip timing commentary when schedule data or a matching game ID is unavailable.
3. Analyze the ESPN data accurately. Verify winners, losers, scores, margins, superlatives, starters, bench points, transactions, streaks, and playoff context against the source data. Never invent a stat or use data from another league or season.
4. Create these files under `{league-key}/{seasonId}/week-{week}/`: `data.json` with the fetched league response, `stats.json` with computed and verified stats, `players.json` with player-level analysis, and `recap.md` containing the final Teams-ready Markdown recap.
5. Keep each recap under approximately 500 words, funny but PG-13 and work-appropriate. Use the requested league name, actual numbers, owner first names, consistent team names, and the weekly persona from the repository agent instructions.
6. Do not modify config, workflow files, agent instructions, secrets, or unrelated files. Do not write credentials into any output.
7. After all leagues are complete, call `create_pull_request` once with a concise summary and the generated recap paths. Create no pull request if no files changed. If the fetch tool cannot obtain a league's data, stop without partial output and explain the missing data in the workflow result.
