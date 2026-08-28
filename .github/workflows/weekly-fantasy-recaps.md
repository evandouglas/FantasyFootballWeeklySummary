---
name: Weekly Fantasy Football Recaps
description: Fetch ESPN results and create reviewed weekly recaps for every configured league
on:
  schedule:
    - cron: "0 14 * * 2"
  workflow_dispatch:
    inputs:
      week:
        description: "Force this week number for every league (testing only; leave blank to infer automatically)"
        required: false
        type: string
      season:
        description: "Force this season year for every league (testing only; leave blank to use config.json)"
        required: false
        type: string
permissions:
  contents: read
  copilot-requests: write
strict: true
model: claude-sonnet-5
engine:
  id: copilot
  agent: fantasy-football
max-ai-credits: 500
max-turns: 60
network:
  allowed:
    - defaults
    - github
    - lm-api-reads.fantasy.espn.com
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
    - cp
    - date
    - ls
    - mkdir
    - find
    - head
    - tail
    - grep
    - wc
    - jq
    - python3
mcp-scripts:
  fetch-espn-leagues:
    description: Fetch the current completed-week ESPN data for every league in config.json and write each league's raw data.json directly to its final path. Returns only small per-league summaries, never the raw payload, so responses stay small. Credentials are isolated to this read-only tool and are never returned.
    inputs:
      week_override:
        type: number
        required: false
        description: Force this week number for every league instead of inferring the latest completed week. For testing only.
      season_override:
        type: number
        required: false
        description: Force this season year for every league instead of the automatically inferred current NFL season year. For testing only.
    py: |
      import json
      import os
      from datetime import datetime, timezone
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
      views = ["mMatchupScore", "mTeam", "mBoxscore", "mTransactions2"]
      week_override = inputs.get("week_override")
      season_override = inputs.get("season_override")

      def infer_season_year():
          # NFL seasons start in the fall and finish early the following year
          now = datetime.now(timezone.utc)
          return now.year - 1 if now.month < 3 else now.year

      def fetch(url):
          with urlopen(Request(url, headers=headers), timeout=60) as response:
              return json.load(response)

      summaries = {}
      for key, league in config.get("leagues", {}).items():
          effective_season = int(season_override) if season_override else infer_season_year()
          params = {"view": views}
          if week_override:
              week = int(week_override)
          else:
              metadata_url = base.format(season=effective_season, league=league["leagueId"]) + "?" + urlencode(params, doseq=True)
              metadata = fetch(metadata_url)
              status = metadata.get("status", {})
              week = next((status.get(name) for name in ("previousScoringPeriod", "latestScoringPeriod", "currentMatchupPeriod") if isinstance(status.get(name), int) and status.get(name) > 0), None)
              if week is None:
                  raise RuntimeError(f"ESPN did not provide a completed matchup period for {key}")
          params["scoringPeriodId"] = str(week)
          data_url = base.format(season=effective_season, league=league["leagueId"]) + "?" + urlencode(params, doseq=True)
          data = fetch(data_url)

          output_dir = root / key / str(effective_season) / f"week-{week}"
          output_dir.mkdir(parents=True, exist_ok=True)
          (output_dir / "data.json").write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")

          teams = data.get("teams", [])
          summaries[key] = {
              "seasonId": effective_season,
              "week": week,
              "data_path": str(output_dir.relative_to(root) / "data.json"),
              "team_count": len(teams),
          }

      print(json.dumps(summaries, ensure_ascii=True))
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
      - "*/*/week-*/stats.json"
      - "*/*/week-*/players.json"
      - "*/*/week-*/recap.md"
    protected-files: blocked
    fallback-as-issue: false
---

# Weekly Fantasy Football Recaps

Run the `fetch-espn-leagues` tool once. For every league in the root `config.json`, it writes the raw ESPN response directly to `{league-key}/{seasonId}/week-{week}/data.json` and returns only a small per-league summary (season, week, data path, team count) — never the raw payload. Process every league in that summary, never just the first one. The tool keeps `ESPN_SWID` and `ESPN_S2` outside the agent and does not return them.

Use repo memory at `/tmp/gh-aw/repo-memory-default/history/` for long-term trend history. For each league and season, read and update `history/{league-key}-{seasonId}.json` with only verified week number, team score, winner/loser, and lowest-scorer results. This history branch is independent of the recap pull request and must be used when checking repeat lowest scorers or season trends. Never store credentials, cookies, raw API responses, owner personal data beyond what is needed for the trend, or generated prose in repo memory.

For each league:

1. Determine the week and season for every league. Manual overrides (for testing): week = `${{ github.event.inputs.week }}`, season = `${{ github.event.inputs.season }}`. If either value is non-empty, call `fetch-espn-leagues` passing it as `week_override` and/or `season_override` for every league. Otherwise call `fetch-espn-leagues` with no overrides; it infers the current NFL season year automatically and returns the week for each league. Do not ask the user for a week or season.
2. Load the schedule for the season the fetch tool returned: look for `nfl-schedule-{seasonId}.json` at the workspace root first (using that returned `seasonId`), and fall back to the root `nfl-schedule.json` if the season-specific file does not exist. Filter its raw `events[]` to the returned week. In the cached ESPN shape, `event.season.type` is normally integer `2` for regular season, `event.week.number` is the week, and `event.id` is the game ID. Skip timing commentary when no schedule file is found or no matching game ID is available.
3. `data.json` is already written by `fetch-espn-leagues` at `{league-key}/{seasonId}/week-{week}/data.json`; read it directly from disk (with `jq`/`python3`) to compute stats — do not copy or re-fetch it. Before anything else, dump `data.json`'s top-level `transactions[]` array for this league and actually look at it (e.g. `python3 -c "import json; d=json.load(open(path)); print(json.dumps(d.get('transactions', []), indent=2))"`) — this is a required, non-skippable step, not something to infer from the schedule or skip if time is tight. Use that raw output to decide what trades to report, per the Trades rules in the repository agent instructions.
4. Analyze the ESPN data accurately. Verify winners, losers, scores, margins, superlatives, starters, bench points, transactions, streaks, and playoff context against the source data. Never invent a stat or use data from another league or season.
5. `data.json` is raw working data only and must never be committed or included in the pull request (it is too large and is excluded from `allowed-files`). In the same directory, create `stats.json` with computed and verified stats, `players.json` with player-level analysis, and `recap.md` containing the final Teams-ready Markdown recap — these three files are the only outputs that belong in the pull request.
6. Keep each recap under approximately 500 words, funny but PG-13 and work-appropriate. Use the requested league name, actual numbers, owner first names, consistent team names, and the weekly persona from the repository agent instructions.
7. Do not modify config, workflow files, agent instructions, secrets, `scripts/`, or unrelated files. Do not write credentials into any output. Treat `scripts/lineup_efficiency.py` as read-only during a recap run: run it as-is via `python3`. If it errors or produces obviously wrong output, skip the Most/Least Accurate Lineup awards for that league this run, note in the workflow result that the script needs a manual look, and continue — never edit the script yourself.
8. After all leagues are complete, call `create_pull_request` once with a concise summary and the generated recap paths. Create no pull request if no files changed. If the fetch tool cannot obtain a league's data, stop without partial output and explain the missing data in the workflow result.
