"""
Test NFL data from ESPN's free API before building the full ranker.
No API key needed, no credit cost. Confirms the data shape.
"""
import requests, json

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
COMMON = "https://site.api.espn.com/apis/common/v3/sports/football/nfl"
H = {}   # ESPN 403s spoofed UAs; plain request works


def get(url, params=None):
    r = requests.get(url, params=params or {}, headers=H, timeout=15)
    r.raise_for_status()
    return r.json()


# 1. This week's games
print("[1] SCOREBOARD")
sb = get(f"{SITE}/scoreboard")
events = sb.get("events", [])
print(f"    Games this week: {len(events)}")
for e in events[:4]:
    comp = (e.get("competitions") or [{}])[0]
    cs = comp.get("competitors", [])
    home = next((c['team']['displayName'] for c in cs if c.get('homeAway')=='home'), '?')
    away = next((c['team']['displayName'] for c in cs if c.get('homeAway')=='away'), '?')
    status = e.get("status", {}).get("type", {}).get("description", "")
    print(f"      {away} @ {home} — {e.get('date','')[:10]} ({status})")

if not events:
    print("    No games — NFL may not have posted this week yet.")
    raise SystemExit

# 2. A team roster (get first home team's id)
comp = (events[0].get("competitions") or [{}])[0]
home = next((c for c in comp.get("competitors", []) if c.get("homeAway")=="home"), {})
team_id = home.get("team", {}).get("id")
team_name = home.get("team", {}).get("displayName", "")
print(f"\n[2] ROSTER for {team_name} (id {team_id})")
roster = get(f"{SITE}/teams/{team_id}/roster")
skill = []
for grp in roster.get("athletes", []):
    for it in grp.get("items", []):
        pos = it.get("position", {}).get("abbreviation", "")
        if pos in ("QB","RB","WR","TE"):
            skill.append((it.get("id"), it.get("displayName"), pos))
print(f"    Skill players found: {len(skill)}")
for pid, name, pos in skill[:6]:
    print(f"      {pos:3} {name} (id {pid})")

if not skill:
    print("    No skill players parsed — roster shape differs.")
    raise SystemExit

# 3. Game log for one player — try current season, then prior
test_id, test_name, test_pos = skill[0]
print(f"\n[3] GAMELOG for {test_name} ({test_pos})")
for season in (2026, 2025):
    gl = get(f"{COMMON}/athletes/{test_id}/gamelog", params={"season": season})
    labels = gl.get("labels", []) or gl.get("names", [])
    n_games = 0
    sample = None
    for st in gl.get("seasonTypes", []):
        for cat in st.get("categories", []):
            evs = cat.get("events", [])
            n_games += len(evs)
            if evs and not sample:
                sample = evs[0].get("stats", [])
    print(f"    Season {season}: {n_games} games | labels: {labels[:8]}")
    if sample:
        print(f"      sample stat row: {sample[:8]}")
    if n_games:
        break

print("\nDone. If [1][2][3] show real data, the NFL build will work.")
print("Note: if 2026 has 0 games (Week 1), it correctly falls back to 2025.")
