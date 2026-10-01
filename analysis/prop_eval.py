"""
analysis/prop_eval.py

Empirical hit rates at ANY line, from a player's real game logs. Lets us grade
the full book ladder (49.5 / 64.5 / 79.5 …) instead of one hardcoded safe line,
so we can find the best-VALUE line, not just the safest. ESPN only — free.
"""

from analysis.td_data import _fetch_gamelog

# our book market -> the ESPN game-log stat column
STAT_KEY = {
    "player_rush_yds": "rushingYards",
    "player_receptions": "receptions",
    "player_reception_yds": "receivingYards",
}


def game_values(player_id, stat_key):
    """List of a player's per-game values for a stat (regular season)."""
    try:
        gl = _fetch_gamelog(player_id)
    except Exception:
        return []
    names = gl.get("names") or []
    if stat_key not in names:
        return []
    idx = names.index(stat_key)
    vals = []
    for season in gl.get("seasonTypes") or []:
        if "regular season" not in (season.get("displayName") or "").lower():
            continue
        for cat in season.get("categories", []):
            for ev in cat.get("events", []):
                st = ev.get("stats")
                if st and len(st) == len(names):
                    try:
                        vals.append(float(st[idx]))
                    except Exception:
                        pass
    return vals


def hit_rate(vals, line):
    """Fraction of games the player cleared `line` (>=)."""
    if not vals:
        return None
    return sum(1 for v in vals if v >= line) / len(vals)
