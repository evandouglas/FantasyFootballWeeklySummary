#!/usr/bin/env python3
"""Compute each team's lineup efficiency (optimal vs. actual starting points) for one ESPN week.

Solves the real assignment problem (which roster entry should fill which starting slot to
maximize points) respecting each player's `eligibleSlots`, instead of approximating with
same-position comparisons. Roster sizes are small enough to solve exactly via memoized search.

Usage:
    python3 scripts/lineup_efficiency.py <path-to-data.json> <week>

Prints JSON to stdout keyed by ESPN teamId:
    {"<teamId>": {"actual_points": float, "optimal_points": float, "accuracy_pct": float}, ...}

Resolve teamId to a team name/owner separately from data["teams"] when writing the recap.
"""
import json
import sys
from functools import lru_cache

BENCH_SLOTS = {20, 21}  # 20 = BE (bench), 21 = IR


def week_points(entry, week):
    pool = entry.get("playerPoolEntry", {})
    if "appliedStatTotal" in pool:
        return float(pool["appliedStatTotal"])
    for stat in pool.get("player", {}).get("stats", []):
        if stat.get("scoringPeriodId") == week and stat.get("statSourceId") == 0:
            return float(stat.get("appliedTotal", 0.0))
    return 0.0


def starting_slots(data, week):
    """Determine the league's starting-lineup slot composition.

    Prefer settings.rosterSettings.lineupSlotCounts when present. Some cached ESPN
    responses omit rosterSettings entirely, so fall back to inferring the slot counts
    from the max number of players actually started in each non-bench slot across all
    teams' rosters for this week (this reflects the league's real lineup requirements).
    """
    counts = data.get("settings", {}).get("rosterSettings", {}).get("lineupSlotCounts", {})
    if counts:
        return [
            int(slot_id)
            for slot_id, count in counts.items()
            if int(slot_id) not in BENCH_SLOTS
            for _ in range(count)
        ]

    from collections import Counter
    observed = Counter()
    for m in data.get("schedule", []):
        if m.get("matchupPeriodId") != week:
            continue
        for side in ("home", "away"):
            roster = m.get(side, {}).get("rosterForCurrentScoringPeriod")
            if not roster:
                continue
            side_counts = Counter(
                e["lineupSlotId"] for e in roster.get("entries", [])
                if e.get("lineupSlotId") not in BENCH_SLOTS
            )
            for slot_id, cnt in side_counts.items():
                observed[slot_id] = max(observed[slot_id], cnt)

    return [slot_id for slot_id, cnt in observed.items() for _ in range(cnt)]


def best_lineup(slots, candidates):
    """Max total points achievable filling `slots` from `candidates`, respecting eligibility."""

    @lru_cache(maxsize=None)
    def solve(slot_idx, used_mask):
        if slot_idx == len(slots):
            return 0.0
        slot_id = slots[slot_idx]
        best = None
        for i, cand in enumerate(candidates):
            if used_mask & (1 << i) or slot_id not in cand["eligible_slots"]:
                continue
            total = cand["points"] + solve(slot_idx + 1, used_mask | (1 << i))
            if best is None or total > best:
                best = total
        # No eligible candidate left for this slot (e.g. bye-heavy roster) -> leave it empty.
        return best if best is not None else solve(slot_idx + 1, used_mask)

    result = solve(0, 0)
    solve.cache_clear()
    return result


def team_roster_entries(data, team_id, week):
    """ESPN's per-week roster lives on the matchup side (schedule[]), not team["roster"]
    (which is only populated for the team the requester owns). Pull entries from the
    matchup period's rosterForCurrentScoringPeriod for the given teamId."""
    for m in data.get("schedule", []):
        if m.get("matchupPeriodId") != week:
            continue
        for side in ("home", "away"):
            side_data = m.get(side, {})
            if side_data.get("teamId") == team_id:
                roster = side_data.get("rosterForCurrentScoringPeriod") or side_data.get("rosterForMatchupPeriod")
                if roster:
                    return roster.get("entries", [])
    return []


def team_efficiency(entries, slots, week):
    candidates = []
    actual_points = 0.0
    for entry in entries:
        lineup_slot = entry.get("lineupSlotId")
        if lineup_slot == 21:  # IR players aren't eligible to move into a starting slot
            continue
        pts = week_points(entry, week)
        eligible = set(entry.get("playerPoolEntry", {}).get("player", {}).get("eligibleSlots", []))
        candidates.append({"points": pts, "eligible_slots": eligible})
        if lineup_slot not in BENCH_SLOTS:
            actual_points += pts

    optimal_points = best_lineup(slots, candidates)
    accuracy = (actual_points / optimal_points * 100.0) if optimal_points else 0.0
    return {
        "actual_points": round(actual_points, 2),
        "optimal_points": round(optimal_points, 2),
        "accuracy_pct": round(accuracy, 1),
    }


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/lineup_efficiency.py <path-to-data.json> <week>", file=sys.stderr)
        sys.exit(1)

    data_path, week = sys.argv[1], int(sys.argv[2])
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    slots = starting_slots(data, week)
    results = {}
    for team in data.get("teams", []):
        team_id = team["id"]
        entries = team_roster_entries(data, team_id, week)
        results[str(team_id)] = team_efficiency(entries, slots, week)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
