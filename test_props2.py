"""
Check standard props across several games to find where lines are posted.
Also shows the full alt ladder so we see the real payout range.
~6-8 credits.
"""
import requests
from datetime import datetime
from config.settings import ODDS_API_KEY

BASE = "https://api.the-odds-api.com/v4"
MLB = "baseball_mlb"


def creds(r):
    return r.headers.get("x-requests-remaining", "?")


r = requests.get(f"{BASE}/sports/{MLB}/events", params={"apiKey": ODDS_API_KEY})
events = r.json()
print(f"Events: {len(events)} | credits: {creds(r)}")

# Sort by start time — test the SOONEST games (props more likely posted)
now = datetime.utcnow().isoformat()
events_sorted = sorted(events, key=lambda e: e.get("commence_time", ""))

print("\nSoonest 5 games:")
for e in events_sorted[:5]:
    print(f"  {e.get('commence_time','')} {e['away_team']} @ {e['home_team']}")

# Test standard props on the 3 soonest games
for e in events_sorted[:3]:
    eid = e["id"]
    r = requests.get(
        f"{BASE}/sports/{MLB}/events/{eid}/odds",
        params={
            "apiKey": ODDS_API_KEY, "regions": "us",
            "markets": "batter_hits,batter_total_bases,pitcher_strikeouts",
            "oddsFormat": "american", "bookmakers": "fanduel,draftkings,betmgm",
        },
    )
    books = r.json().get("bookmakers", []) if r.ok else []
    print(f"\n{e['away_team']} @ {e['home_team']} ({e.get('commence_time','')[:16]})")
    print(f"  standard props: {len(books)} books | credits: {creds(r)}")
    if books:
        m = books[0].get("markets", [])
        for mk in m:
            print(f"    {mk['key']}: {len(mk.get('outcomes',[]))} outcomes "
                  f"(book: {books[0]['key']})")
        # Show a sample line with both sides
        for mk in m:
            outs = mk.get("outcomes", [])
            players = {}
            for o in outs:
                players.setdefault(o.get("description"), {})[o.get("name")] = o.get("point"), o.get("price")
            for pl, sides in list(players.items())[:2]:
                print(f"      {pl} {mk['key']}: {sides}")
            break

# Full alt ladder for the soonest game
eid = events_sorted[0]["id"]
r = requests.get(
    f"{BASE}/sports/{MLB}/events/{eid}/odds",
    params={
        "apiKey": ODDS_API_KEY, "regions": "us",
        "markets": "batter_hits_alternate", "oddsFormat": "american",
        "bookmakers": "fanduel,draftkings",
    },
)
print(f"\nFULL alt ladder (soonest game) | credits: {creds(r)}")
if r.ok:
    books = r.json().get("bookmakers", [])
    if books:
        outs = books[0].get("markets", [{}])[0].get("outcomes", [])
        players = {}
        for o in outs:
            players.setdefault(o.get("description"), []).append(
                (o.get("point"), o.get("price")))
        for pl, ladder in list(players.items())[:3]:
            print(f"  {pl}:")
            for point, price in sorted(ladder):
                # implied prob from american odds
                ip = (100/(price+100)) if price > 0 else (-price/(-price+100))
                print(f"     {point}+ hits @ {price:+d}  (~{ip*100:.0f}% implied)")
