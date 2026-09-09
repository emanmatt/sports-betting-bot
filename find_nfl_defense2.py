"""
Check the byteam stats endpoint — one call for all 32 teams. Looking
for opponent yards allowed (true defense strength). Free.
"""
import requests

url = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/statistics/byteam"
for season in (2025, 2026):
    print(f"\n===== season {season} =====")
    r = requests.get(url, params={"season": season}, timeout=15)
    if not r.ok:
        print(f"  [{r.status_code}]")
        continue
    data = r.json()
    print("  requestedSeason:", data.get("requestedSeason", {}).get("year"))
    cats = data.get("categories", [])
    print("  categories:", [c.get("name") for c in cats])
    # show stat names under a defense-ish category
    for c in cats:
        nm = c.get("name", "")
        if "defen" in nm.lower() or "opponent" in nm.lower():
            print(f"\n  category '{nm}' stat labels:")
            for lbl in c.get("labels", [])[:30]:
                print("     ", lbl)
    # peek at one team's row
    teams = data.get("teams", [])
    print(f"\n  teams returned: {len(teams)}")
    if teams:
        t0 = teams[0]
        print("  first team:", t0.get("team", {}).get("displayName"))
        for cat in t0.get("categories", []):
            if "defen" in cat.get("name","").lower() or "opponent" in cat.get("name","").lower():
                print(f"    {cat.get('name')}: {cat.get('values', [])[:15]}")
    if r.ok and teams:
        break

print("\nLooking for opponent passing/rushing yards per game.")
print("If present -> precise defense factor. If not -> we use sacks/INTs/")
print("passes-defended as a solid proxy (confirmed available).")
