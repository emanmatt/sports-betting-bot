"""
data_ingestion/official/nfl_client.py

NFL player + game data from ESPN's free public API (no key needed).
Mirrors the MLB client's role but for football.

Key NFL realities baked in:
  - Tiny sample: 17 games/season, one per week. "Recent form" spans
    the whole season, so we pull season + PRIOR-year stats and weight
    by how much current-season data exists.
  - Position-specific: QB / RB / WR / TE have different prop stats.
  - Week 1 (season start) = zero current data → lean fully on last year.

ESPN endpoints used (public, undocumented but stable):
  site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  site.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{id}/gamelog
  sports.core.api.espn.com for season splits
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
COMMON = "https://site.api.espn.com/apis/common/v3/sports/football/nfl"
# ESPN 403s spoofed browser User-Agents but ALLOWS plain requests.
# So we deliberately send NO custom headers.
HEADERS = {}

CURRENT_SEASON = 2026
PRIOR_SEASON = 2025

# Prop-relevant stats by position
QB_STATS = ["passingYards", "passingTouchdowns", "completions",
            "passingAttempts", "interceptions", "rushingYards"]
SKILL_STATS = ["rushingYards", "rushingAttempts", "receivingYards",
               "receptions", "receivingTargets", "rushingTouchdowns",
               "receivingTouchdowns"]


@dataclass
class NFLGame:
    game_id:      str
    away_team:    str
    home_team:    str
    game_time:    str
    status:       str = ""
    venue:        str = ""
    week:         int = None
    home_team_id: str = None
    away_team_id: str = None


@dataclass
class NFLPlayerLog:
    player_name: str
    player_id:   str
    position:    str
    team:        str
    season:      int
    games:       list = field(default_factory=list)  # list of per-game stat dicts


class NFLClient:
    def __init__(self):
        self.session = requests.Session()
        # Deliberately no custom headers — ESPN blocks spoofed UAs.
        if HEADERS:
            self.session.headers.update(HEADERS)

    def _get(self, url, params=None):
        try:
            r = self.session.get(url, params=params or {}, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"[NFL] {e}")
            return None

    def classify_status(self, status: str) -> str:
        s = (status or "").lower()
        if any(w in s for w in ["final", "completed"]):
            return "final"
        if any(w in s for w in ["in progress", "live", "halftime", "quarter"]):
            return "live"
        return "upcoming"

    def get_todays_games(self) -> list[NFLGame]:
        """Get this week's NFL games from the scoreboard."""
        data = self._get(f"{SITE}/scoreboard")
        if not data:
            return []
        games = []
        for event in data.get("events", []):
            comp = (event.get("competitions") or [{}])[0]
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})
            status = event.get("status", {}).get("type", {}).get("description", "")
            games.append(NFLGame(
                game_id=event.get("id", ""),
                away_team=away.get("team", {}).get("displayName", ""),
                home_team=home.get("team", {}).get("displayName", ""),
                away_team_id=away.get("team", {}).get("id"),
                home_team_id=home.get("team", {}).get("id"),
                game_time=event.get("date", ""),
                status=status,
                venue=comp.get("venue", {}).get("fullName", ""),
                week=(data.get("week", {}) or {}).get("number"),
            ))
        return games

    def get_team_roster(self, team_id: str) -> list[dict]:
        """Get a team's roster with player IDs and positions."""
        if not team_id:
            return []
        data = self._get(f"{SITE}/teams/{team_id}/roster")
        if not data:
            return []
        players = []
        for group in data.get("athletes", []):
            for item in group.get("items", []):
                pos = item.get("position", {}).get("abbreviation", "")
                if pos in ("QB", "RB", "WR", "TE", "FB"):
                    players.append({
                        "id": item.get("id"),
                        "name": item.get("displayName", ""),
                        "position": pos,
                    })
        return players

    def get_player_gamelog(self, player_id: str, season: int = None) -> NFLPlayerLog:
        """
        Get a player's per-game logs for a season. If the current season
        has no games yet (Week 1), returns empty games list — caller
        falls back to prior season.
        """
        season = season or CURRENT_SEASON
        data = self._get(f"{COMMON}/athletes/{player_id}/gamelog",
                        params={"season": season})
        if not data:
            return NFLPlayerLog("", player_id, "", "", season)

        name = data.get("athlete", {}).get("displayName", "") \
            if isinstance(data.get("athlete"), dict) else ""
        pos = data.get("athlete", {}).get("position", {}).get("abbreviation", "") \
            if isinstance(data.get("athlete"), dict) else ""

        games = []
        # ESPN nests game stats in seasonTypes -> categories -> events.
        # IMPORTANT: labels can contain duplicates (two "YDS" = rec + rush),
        # so we store the ordered labels + stats, NOT a dict (which would
        # collapse duplicate keys). The ranker parses by position + order.
        labels = data.get("labels", []) or data.get("names", [])
        for st in data.get("seasonTypes", []):
            for cat in st.get("categories", []):
                for ev in cat.get("events", []):
                    stats = ev.get("stats", [])
                    if stats:
                        games.append({
                            "_labels": labels,
                            "_stats": stats,
                        })

        return NFLPlayerLog(
            player_name=name, player_id=player_id, position=pos,
            team="", season=season, games=games,
        )

    def get_player_stats_with_fallback(self, player_id: str) -> NFLPlayerLog:
        """
        Get current-season logs; if empty (early season), fall back to
        prior season. Returns whichever has data, tagged with its season.
        """
        current = self.get_player_gamelog(player_id, CURRENT_SEASON)
        if current.games:
            return current
        prior = self.get_player_gamelog(player_id, PRIOR_SEASON)
        return prior
