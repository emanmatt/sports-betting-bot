"""
data_ingestion/soft/reddit_client.py

Pulls MLB discussion from Reddit using the PUBLIC JSON API.
No login or API credentials needed — just adds .json to any
subreddit URL. This is Tier 3 (soft) data — sentiment and
breaking chatter, weighted low.

Subreddits: r/baseball, r/MLB, r/sportsbook, plus team subs.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
import time
from datetime import datetime, timezone
from loguru import logger

HEADERS = {
    "User-Agent": "SportsBettingResearch/1.0 (research bot)"
}

# Team subreddits for lineup/injury chatter
TEAM_SUBS = {
    "Yankees": "NYYankees", "Red Sox": "redsox", "Dodgers": "Dodgers",
    "Cubs": "CHICubs", "Mets": "NewYorkMets", "Braves": "Braves",
    "Astros": "Astros", "Phillies": "phillies", "Cardinals": "Cardinals",
    "Giants": "SFGiants", "Padres": "Padres", "Brewers": "Brewers",
    "Guardians": "ClevelandGuardians", "Mariners": "Mariners",
    "Rays": "tampabayrays", "Orioles": "Orioles", "Blue Jays": "Torontobluejays",
}


class RedditClient:
    """Reddit public JSON reader — no auth required."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get_json(self, url: str) -> dict:
        try:
            resp = self.session.get(url, timeout=12)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"[Reddit] Failed {url}: {e}")
            return {}

    def get_subreddit_posts(self, subreddit: str,
                            sort: str = "hot", limit: int = 15) -> list[dict]:
        """Pull recent posts from a subreddit via public JSON."""
        url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
        data = self._get_json(url)
        posts = []
        for child in data.get("data", {}).get("children", []):
            p = child.get("data", {})
            posts.append({
                "title": p.get("title", ""),
                "text": p.get("selftext", "")[:500],
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "created": datetime.fromtimestamp(
                    p.get("created_utc", 0), tz=timezone.utc
                ).isoformat(),
                "url": f"https://reddit.com{p.get('permalink','')}",
                "subreddit": subreddit,
            })
        time.sleep(1)  # Be polite to Reddit
        return posts

    def search_team_news(self, team_name: str) -> list[dict]:
        """
        Search a team's subreddit for lineup/injury/rest chatter.
        """
        # Find the team sub
        sub = None
        for key, subname in TEAM_SUBS.items():
            if key.lower() in team_name.lower():
                sub = subname
                break
        if not sub:
            return []

        posts = self.get_subreddit_posts(sub, sort="hot", limit=15)

        # Filter for relevant keywords
        keywords = ["lineup", "injury", "injured", "IL", "scratch", "rest",
                   "day off", "starting", "out", "questionable", "return"]
        relevant = []
        for post in posts:
            text = (post["title"] + " " + post["text"]).lower()
            if any(kw in text for kw in keywords):
                relevant.append(post)
        return relevant

    def get_gameday_threads(self) -> list[dict]:
        """Get today's game threads from r/baseball for live info."""
        posts = self.get_subreddit_posts("baseball", sort="hot", limit=25)
        return [p for p in posts if "game thread" in p["title"].lower()
                or "lineup" in p["title"].lower()]

    def get_betting_chatter(self) -> list[dict]:
        """Pull MLB betting discussion from r/sportsbook."""
        posts = self.get_subreddit_posts("sportsbook", sort="hot", limit=20)
        return [p for p in posts if "mlb" in (p["title"]+p["text"]).lower()
                or "baseball" in (p["title"]+p["text"]).lower()]

    def search_player_chatter(self, player_name: str) -> list[dict]:
        """
        Find recent posts/comments mentioning a specific player across
        the main betting/baseball subs. Tier 3 soft signal only.
        """
        found = []
        subs = ["sportsbook", "baseball", "MLB"]
        last = player_name.split()[-1] if player_name else ""
        for sub in subs:
            try:
                posts = self.get_subreddit_posts(sub, sort="hot", limit=25)
                for p in posts:
                    text = (p.get("title", "") + " " + p.get("text", "")).lower()
                    if player_name.lower() in text or (last and last.lower() in text):
                        found.append({
                            "player": player_name,
                            "sub": sub,
                            "title": p.get("title", ""),
                            "score": p.get("score", 0),
                            "url": p.get("url", ""),
                        })
            except Exception:
                continue
        return found

    def run_all_sports(self):
        """Compatibility method for scheduler — pulls MLB chatter."""
        try:
            chatter = self.get_betting_chatter()
            logger.info(f"[Reddit] Pulled {len(chatter)} MLB betting posts.")
            return chatter
        except Exception as e:
            logger.warning(f"[Reddit] run_all_sports failed: {e}")
            return []
