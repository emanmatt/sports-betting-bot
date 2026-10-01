"""
build_dvp.py — computes Defense-vs-Position for all 32 teams and caches it to
your database. Run once now (then weekly). Free — ESPN only, no OddsAPI credits.
Takes ~1-2 minutes (reads ~300 game logs in parallel).
    python build_dvp.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from analysis.nfl_ranker import NFLRanker
from analysis.dvp_engine import refresh_dvp, dvp_summary

print("Building Defense-vs-Position (this takes a minute)…")
ranker = NFLRanker()
blob = refresh_dvp(ranker.nfl)
print(f"Done. {blob['n_teams']} defenses, updated {blob['updated']}.")
print("\nSample (first 4 defenses):")
for name in list(blob["name_to_abbr"])[:4]:
    s = dvp_summary(blob, name)
    if s:
        print(" ", s)
print("\nCached to DB. The analysis will now use these ranks automatically.")
