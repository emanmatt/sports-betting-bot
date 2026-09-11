"""
Directly test NFL ranking + logging, with full error output (no silent
except). Tells us exactly why NFL rows = 0.
"""
import sys, traceback
sys.path.insert(0, ".")

from analysis.nfl_ranker import NFLRanker
from analysis.track_record import TrackRecord

ranker = NFLRanker()
games = ranker.nfl.get_todays_games()
print(f"NFL games this week: {len(games)}")

# Rank ONE game
upcoming = [g for g in games if ranker.nfl.classify_status(g.status) != "final"]
if not upcoming:
    print("No upcoming games — all may be final. Try a different week.")
    sys.exit()

g = upcoming[0]
print(f"Ranking: {g.away_team} @ {g.home_team}")

all_props = []
for team_id, team_name, opp_name in [
    (g.home_team_id, g.home_team, g.away_team),
    (g.away_team_id, g.away_team, g.home_team),
]:
    try:
        if ranker.inactives:
            ranker.inactives.load_team(team_id)
        roster = ranker.nfl.get_team_roster(team_id)
        print(f"  {team_name}: {len(roster)} players on roster")
        for player in roster:
            props = ranker.rank_player(player, team_name, opp_name,
                                       f"{g.away_team} @ {g.home_team}")
            all_props.extend(props)
    except Exception as e:
        print(f"  ERROR on {team_name}: {e}")
        traceback.print_exc()

print(f"\nTotal props ranked: {len(all_props)}")
if all_props:
    p = all_props[0]
    print(f"Sample prop: {p.player_name} {p.prop_label} score={p.score}")
    # check the shim attributes log_predictions needs
    for attr in ["player_name","prop_stat","prop_label","prop_line","is_pitcher",
                 "team","opponent","game_matchup","tier","score","l10_rate"]:
        try:
            v = getattr(p, attr)
            print(f"   {attr} = {v}")
        except Exception as e:
            print(f"   {attr} = MISSING! {e}")

    # Now try logging WITH full error output
    print("\nAttempting to log...")
    try:
        tr = TrackRecord()
        n = tr.log_predictions(all_props, top_n=20, sport="NFL")
        tr.close()
        print(f"✓ Logged {n} NFL predictions")
    except Exception as e:
        print(f"✗ LOGGING FAILED: {e}")
        traceback.print_exc()
else:
    print("No props ranked — that's why nothing logged.")
    print("Likely: players lack sufficient data, or roster/gamelog issue.")
