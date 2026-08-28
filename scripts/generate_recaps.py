import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
AGENT_PATH = ROOT / ".github" / "agents" / "fantasy-football.agent.md"
SCHEDULE_PATH = ROOT / "nfl-schedule.json"
BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league}"
MODEL_URL = os.environ.get("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")
VIEWS = "mMatchupScore,mTeam,mBoxscore,mTransactions2"


def request_json(url, headers):
    request = Request(url, headers=headers)
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def league_url(league_id, season_id, week=None):
    params = {"view": VIEWS}
    if week is not None:
        params["scoringPeriodId"] = str(week)
    return BASE_URL.format(league=league_id, season=season_id) + "?" + urlencode(params)


def espn_headers():
    swid = os.environ.get("ESPN_SWID")
    espn_s2 = os.environ.get("ESPN_S2")
    if not swid or not espn_s2:
        raise RuntimeError("ESPN_SWID and ESPN_S2 Actions Secrets are required")
    return {
        "Accept": "application/json",
        "Cookie": f"SWID={swid}; espn_s2={espn_s2}",
        "User-Agent": "FantasyFootballWeeklySummary/1.0",
    }


def infer_week(payload):
    status = payload.get("status", {})
    for key in ("previousScoringPeriod", "latestScoringPeriod", "currentMatchupPeriod"):
        value = status.get(key)
        if isinstance(value, int) and value > 0:
            return value
    raise RuntimeError("ESPN did not provide a completed matchup period")


def load_schedule(season_id, week):
    if not SCHEDULE_PATH.exists():
        return []
    schedule = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    events = schedule.get("events", [])
    matching_events = []
    for event in events:
        season = event.get("season", {})
        season_type = season.get("type")
        if isinstance(season_type, dict):
            season_type = season_type.get("type")
        if (
            season_type == 2
            and event.get("week", {}).get("number") == week
            and str(season.get("year")) == str(season_id)
        ):
            matching_events.append(event)
    return matching_events


def generate_recap(league, week, data, schedule, agent_instructions):
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is missing; add it under repository Secrets, not Variables")
    request_body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "temperature": 0.8,
        "messages": [
            {
                "role": "system",
                "content": agent_instructions,
            },
            {
                "role": "user",
                "content": json.dumps({
                    "task": "Generate the weekly recap for this league. Return only the final Markdown block.",
                    "league": league,
                    "week": week,
                    "scheduleEvents": schedule,
                    "espnLeagueData": data,
                }, ensure_ascii=True),
            },
        ],
    }
    request = Request(
        MODEL_URL,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_api_key}",
        },
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    return result["choices"][0]["message"]["content"].strip()


def write_results(key, league, season_id, week, data, recap):
    output_dir = ROOT / key / str(season_id) / f"week-{week}"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (output_dir / "recap.md").write_text(recap + "\n", encoding="utf-8")


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    agent_instructions = AGENT_PATH.read_text(encoding="utf-8")
    headers = espn_headers()
    generated = []

    for key, league in config.get("leagues", {}).items():
        season_id = league["seasonId"]
        league_id = league["leagueId"]
        metadata = request_json(league_url(league_id, season_id), headers)
        week = infer_week(metadata)
        data = request_json(league_url(league_id, season_id, week), headers)
        schedule = load_schedule(season_id, week)
        recap = generate_recap({"key": key, **league}, week, data, schedule, agent_instructions)
        write_results(key, league, season_id, week, data, recap)
        generated.append(f"{key} week {week}")

    print("Generated: " + ", ".join(generated))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Generation failed: {error}", file=sys.stderr)
        sys.exit(1)
