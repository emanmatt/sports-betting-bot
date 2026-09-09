"""
Diagnose ESPN 403 — try different hosts, headers, and paths to find
one that returns NFL data. No cost.
"""
import requests

attempts = [
    # (label, url, headers)
    ("site.api plain",
     "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
     {}),
    ("site.api + browser UA",
     "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
     {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
      "Accept": "application/json",
      "Referer": "https://www.espn.com/"}),
    ("cdn.espn core",
     "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events",
     {"User-Agent": "Mozilla/5.0"}),
    ("site.web.api",
     "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
     {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
      "Accept": "application/json"}),
    ("cdn.espn scoreboard",
     "https://cdn.espn.com/core/nfl/scoreboard?xhr=1",
     {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"}),
]

for label, url, headers in attempts:
    try:
        r = requests.get(url, headers=headers, timeout=15)
        status = r.status_code
        size = len(r.content)
        # quick peek: does it look like JSON with events?
        marker = ""
        if r.ok:
            try:
                j = r.json()
                if "events" in j:
                    marker = f"✓ has 'events' ({len(j['events'])})"
                elif "items" in j:
                    marker = f"✓ has 'items' ({len(j['items'])})"
                elif "content" in j:
                    marker = "✓ has 'content' (cdn wrapper)"
                else:
                    marker = f"keys: {list(j.keys())[:5]}"
            except Exception:
                marker = "not JSON"
        print(f"[{status}] {label:22} {size:>7}b  {marker}")
    except Exception as e:
        print(f"[ERR] {label:22} {str(e)[:50]}")

print("\nWhichever shows [200] with events/items — that's the one to use.")
