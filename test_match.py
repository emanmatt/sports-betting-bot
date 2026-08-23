"""Does the ranker match a real batter? Tests the exact lookup path."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from analysis.hits_ranker import HitsRanker
from data_ingestion.official.mlb_client import MLBClient

# 1. Get today's confirmed lineups and print the actual batter names
mlb = MLBClient()
games = mlb.get_todays_games()
print(f"{len(games)} games today\n")

batter_names = []
for g in games[:5]:
    lineup = mlb.get_lineup(g.game_pk)
    if lineup["confirmed"]:
        print(f"CONFIRMED: {g.away_team} @ {g.home_team}")
        for b in lineup["home"][:3] + lineup["away"][:3]:
            print(f"   lineup name: '{b['name']}'")
            batter_names.append(b["name"])
        break

# 2. Test if ranker finds hit history for those exact names
print("\n--- Testing ranker lookup ---")
ranker = HitsRanker()
for name in batter_names[:5]:
    hist = ranker._get_batter_hit_history(name)
    if hist:
        print(f"✅ '{name}': L10 {hist['l10_hit_rate']}%, {hist['games_logged']} games")
    else:
        print(f"❌ '{name}': NO MATCH in logs")

# 3. Show what names ARE actually in the logs (first 10)
print("\n--- Sample names stored in logs ---")
if hasattr(ranker, "_logs_by_name"):
    for nm in list(ranker._logs_by_name.keys())[:10]:
        print(f"   stored: '{nm}'")
ranker.close()
