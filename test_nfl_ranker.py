"""
Test the NFL ranker on real players (a QB and a WR/TE) to confirm
parsing produces sane numbers before wiring into the dashboard.
Free — ESPN data only.
"""
import sys
sys.path.insert(0, ".")

from data_ingestion.official.nfl_client import NFLClient
from analysis.nfl_ranker import NFLRanker, _parse_qb_game, _parse_skill_game

nfl = NFLClient()
ranker = NFLRanker()

# Get one game, one roster
games = nfl.get_todays_games()
print(f"Games this week: {len(games)}")
g = games[0]
print(f"Testing: {g.away_team} @ {g.home_team}\n")

roster = nfl.get_team_roster(g.home_team_id)
qbs = [p for p in roster if p["position"] == "QB"]
wrs = [p for p in roster if p["position"] in ("WR", "TE")]

# --- Inspect QB label structure (we haven't seen it yet) ---
if qbs:
    qb = qbs[0]
    print(f"=== QB: {qb['name']} ===")
    log = nfl.get_player_stats_with_fallback(qb["id"])
    print(f"  data season: {log.season}, games: {len(log.games)}")
    if log.games:
        g0 = log.games[0]
        print(f"  QB gamelog LABELS: {g0['_labels']}")
        print(f"  QB sample stats:   {g0['_stats']}")
        parsed = _parse_qb_game(g0["_labels"], g0["_stats"])
        print(f"  parsed -> {parsed}")
    print()
    ranks = ranker.rank_player(qb, g.home_team, g.away_team,
                               f"{g.away_team} @ {g.home_team}")
    for r in ranks:
        print(f"    {r.prop_label}: hit {r.hit_rate}% avg {r.avg_value} "
              f"({r.games}g, {r.data_season}) score {r.score} [{r.tier}]")

# --- Skill player ---
if wrs:
    wr = wrs[0]
    print(f"\n=== {wr['position']}: {wr['name']} ===")
    log = nfl.get_player_stats_with_fallback(wr["id"])
    if log.games:
        g0 = log.games[0]
        print(f"  labels: {g0['_labels']}")
        print(f"  sample: {g0['_stats']}")
        print(f"  parsed -> {_parse_skill_game(g0['_labels'], g0['_stats'])}")
    ranks = ranker.rank_player(wr, g.home_team, g.away_team,
                               f"{g.away_team} @ {g.home_team}")
    for r in ranks:
        print(f"    {r.prop_label}: hit {r.hit_rate}% avg {r.avg_value} "
              f"({r.games}g) score {r.score} [{r.tier}]")

print("\nCheck: do the parsed stats and hit rates look realistic?")
print("(e.g. a starting QB ~250 pass yds/game, a WR1 ~5 rec/game)")
