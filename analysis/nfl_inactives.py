"""
analysis/nfl_inactives.py

NFL inactive / injury-status checker.

Critical for football props: unlike MLB (daily games, minor day-to-day
stuff), an NFL player is a binary — ACTIVE or a healthy scratch / ruled
out. Betting a prop on a player who's inactive is an automatic loss.
Official inactives post ~90 minutes before kickoff, but injury
designations (Out / Doubtful / Questionable) are known earlier in the week.

This pulls ESPN's injury report per team so the ranker can:
  - DROP players ruled Out / Doubtful (won't play, or unlikely)
  - FLAG Questionable (game-time decision — verify before betting)

ESPN injuries endpoint (free): team detail includes an injuries list,
or the dedicated injuries endpoint.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from loguru import logger

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"


class NFLInactives:
    def __init__(self):
        self.session = requests.Session()  # no custom headers (ESPN 403s UAs)
        self._cache = {}   # player_name -> status
        self._loaded_teams = set()

    def _get(self, url, params=None):
        try:
            r = self.session.get(url, params=params or {}, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"[NFLInactives] {e}")
            return None

    def load_team(self, team_id: str):
        """Load a team's injury report into the cache."""
        if not team_id or team_id in self._loaded_teams:
            return
        data = self._get(f"{SITE}/teams/{team_id}")
        if not data:
            self._loaded_teams.add(team_id)
            return
        team = data.get("team", {})
        for inj in team.get("injuries", []):
            athlete = inj.get("athlete", {})
            name = athlete.get("displayName", "") if isinstance(athlete, dict) else ""
            status = inj.get("status", "") or inj.get("type", {}).get("description", "")
            if name:
                self._cache[name] = status
        self._loaded_teams.add(team_id)

    def status_for(self, player_name: str) -> str:
        """Return injury status string for a player, or '' if healthy/unknown."""
        return self._cache.get(player_name, "")

    def classify(self, status: str) -> str:
        """
        Classify a status into: out / doubtful / questionable / ok.
        Drives whether the ranker drops or flags the player.
        """
        s = (status or "").lower()
        if any(w in s for w in ["out", "injured reserve", "ir", "suspend",
                                "did not", "inactive"]):
            return "out"
        if "doubtful" in s:
            return "doubtful"
        if "questionable" in s:
            return "questionable"
        return "ok"

    def adjustment(self, player_name: str) -> tuple:
        """
        Return (score_adjustment, flag_text) for a player's status.
        Out/Doubtful → big penalty (effectively drop). Questionable → flag.
        """
        status = self.status_for(player_name)
        cls = self.classify(status)
        if cls == "out":
            return -100, "🚫 OUT"
        if cls == "doubtful":
            return -50, "⚠️ Doubtful"
        if cls == "questionable":
            return -8, "⚠️ Questionable"
        return 0, ""
