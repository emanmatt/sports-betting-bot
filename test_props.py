"""
Minimal test: does OddsAPI return MLB props + alt lines?
Costs ~2-3 credits total. Run once to confirm before the full build.
"""
import requests
from config.settings import ODDS_API_KEY

BASE = "https://api.the-odds-api.com/v4"
MLB = "baseball_mlb"


def creds(r):
    return r.headers.get("x-requests-remaining", "?")


# 1. Get today's events (1 credit)
r = requests.get(f"{BASE}/sports/{MLB}/events", params={"apiKey": ODDS_API_KEY})
r.raise_for_status()
events = r.json()
print(f"[1] Events today: {len(events)} | credits left: {creds(r)}")
if not events:
    print("No MLB games today — try again on a game day.")
    raise SystemExit

event_id = events[0]["id"]
print(f"    Testing game: {events[0]['away_team']} @ {events[0]['home_team']}")

# 2. Standard props for ONE game (a few credits)
r = requests.get(
    f"{BASE}/sports/{MLB}/events/{event_id}/odds",
    params={
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "batter_hits,pitcher_strikeouts",
        "oddsFormat": "american",
        "bookmakers": "fanduel,draftkings",
    },
)
print(f"\n[2] Standard props | credits left: {creds(r)}")
if r.ok:
    data = r.json()
    books = data.get("bookmakers", [])
    print(f"    Books returned: {[b['key'] for b in books]}")
    if books:
        for m in books[0].get("markets", []):
            outs = m.get("outcomes", [])
            print(f"    {m['key']}: {len(outs)} outcomes")
            for o in outs[:3]:
                print(f"       {o.get('description')} {o.get('name')} "
                      f"{o.get('point')} @ {o.get('price')}")
else:
    print(f"    ERROR {r.status_code}: {r.text[:200]}")

# 3. ALT lines for one game (a few credits)
r = requests.get(
    f"{BASE}/sports/{MLB}/events/{event_id}/odds",
    params={
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "batter_hits_alternate",
        "oddsFormat": "american",
        "bookmakers": "fanduel,draftkings",
    },
)
print(f"\n[3] ALTERNATE lines | credits left: {creds(r)}")
if r.ok:
    data = r.json()
    books = data.get("bookmakers", [])
    if books:
        for m in books[0].get("markets", []):
            outs = m.get("outcomes", [])
            print(f"    {m['key']}: {len(outs)} alt outcomes")
            # Show the alt ladder for the first player
            first_player = outs[0].get("description") if outs else None
            ladder = [(o.get("point"), o.get("name"), o.get("price"))
                      for o in outs if o.get("description") == first_player]
            print(f"    Alt ladder for {first_player}:")
            for point, name, price in ladder[:8]:
                print(f"       {name} {point} @ {price}")
    else:
        print("    No alt lines returned (some books/games don't offer them)")
else:
    print(f"    ERROR {r.status_code}: {r.text[:200]}")

print("\nDone. If [2] and [3] show real numbers, the full build will work.")
