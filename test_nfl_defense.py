"""
Test that NFL defensive stats actually come back and parse.
Free ESPN data. Confirms the matchup factor will work before wiring it in.
"""
import sys
sys.path.insert(0, ".")
import requests

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"


def get(url, params=None):
    r = requests.get(url, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


# Get one team id
teams_data = get(f"{SITE}/teams")
first = None
for sport in teams_data.get("sports", []):
    for league in sport.get("leagues", []):
        for t in league.get("teams", []):
            team = t.get("team", {})
            first = (team.get("id"), team.get("displayName"))
            break
        if first: break
    if first: break

print(f"Testing team: {first[1]} (id {first[0]})")

# Try the statistics endpoint for 2025
for season in (2026, 2025):
    print(f"\n=== Season {season} ===")
    stats = get(f"{SITE}/teams/{first[0]}/statistics", params={"season": season})
    if not stats:
        print("  no data")
        continue
    # Explore the structure
    print(f"  top-level keys: {list(stats.keys())[:8]}")
    results = stats.get("results", stats)
    if isinstance(results, dict):
        print(f"  results keys: {list(results.keys())[:8]}")
        statsblob = results.get("stats", {})
        if isinstance(statsblob, dict):
            cats = statsblob.get("categories", [])
            print(f"  categories: {[c.get('name') for c in cats]}")
            # Look for opponent/defensive stats
            for cat in cats:
                for s in cat.get("stats", [])[:40]:
                    nm = s.get("name", "")
                    if any(k in nm.lower() for k in
                           ["opponent", "passingyards", "rushingyards", "yardspergame"]):
                        print(f"    {cat.get('name')}.{nm} = {s.get('value')} "
                              f"({s.get('displayValue')})")
    # Only need one season with data
    if stats:
        break

print("\nLooking for opponent pass/rush yards per game — if you see them above,")
print("the defense matchup factor will work. If not, we adjust the parser.")
