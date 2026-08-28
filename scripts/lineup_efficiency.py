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


def starting_slots(settings):
    counts = settings.get("rosterSettings", {}).get("lineupSlotCounts", {})
    return [
        int(slot_id)
        for slot_id, count in counts.items()
        if int(slot_id) not in BENCH_SLOTS
        for _ in range(count)
    ]


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


def team_efficiency(team, slots, week):
    candidates = []
    actual_points = 0.0
    for entry in team.get("roster", {}).get("entries", []):
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

    slots = starting_slots(data.get("settings", {}))
    results = {
        str(team["id"]): team_efficiency(team, slots, week)
        for team in data.get("teams", [])
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
