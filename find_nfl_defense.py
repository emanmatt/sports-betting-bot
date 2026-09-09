"""
Find where ESPN serves NFL team defensive stats. Tries several known
endpoint shapes. Free, no credits.
"""
import requests, json

def get(url, params=None):
    try:
        r = requests.get(url, params=params or {}, timeout=15)
        return r.status_code, (r.json() if r.ok else None)
    except Exception as e:
        return "ERR", str(e)[:60]

TID = 22  # Arizona
attempts = [
    ("core team stats 2025",
     f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2025/types/2/teams/{TID}/statistics"),
    ("core team record 2025",
     f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2025/types/2/teams/{TID}/record"),
    ("site team detail",
     f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{TID}"),
    ("site core statistics (no season)",
     f"https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/statistics/byteam"),
    ("team stats via web.api",
     f"https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/teams/{TID}/statistics"),
]

for label, url in attempts:
    status, data = get(url)
    marker = ""
    if data and isinstance(data, dict):
        keys = list(data.keys())[:6]
        marker = f"keys: {keys}"
        # dig for anything stats-like
        if "splits" in data:
            marker += " | HAS splits"
        if "results" in data:
            marker += " | HAS results"
        if "statistics" in data:
            marker += " | HAS statistics"
    print(f"[{status}] {label}")
    print(f"      {url}")
    print(f"      {marker}\n")

# For the most promising (core team stats), dig deeper if it worked
status, data = get(attempts[0][1])
if data:
    print("=== Digging into core team stats ===")
    print("top keys:", list(data.keys()))
    splits = data.get("splits", {})
    if splits:
        cats = splits.get("categories", [])
        print("categories:", [c.get("name") for c in cats])
        for cat in cats:
            if cat.get("name") in ("passing", "rushing", "defensive", "defensiveInterceptions"):
                print(f"\n{cat.get('name')} stats:")
                for s in cat.get("stats", [])[:15]:
                    print(f"   {s.get('name')} = {s.get('value')} ({s.get('displayValue')})")
