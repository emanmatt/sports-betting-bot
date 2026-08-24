"""
data_ingestion/official/mlb_client.py

Pulls official MLB data from MLB's free Stats API (no key needed):
  - Confirmed starting lineups
  - Probable pitchers
  - Injury status
  - Game venue (for weather/wind analysis)

This is Tier 1 hard data — the most reliable source.
API base: https://statsapi.mlb.com/api/v1
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger

BASE = "https://statsapi.mlb.com/api/v1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"
}


@dataclass
class MLBGame:
    game_pk:        int
    away_team:      str
    home_team:      str
    game_time:      str
    status:         str
    venue:          str = ""
    venue_id:       int = None
    # Probable pitchers
    home_pitcher:   str = ""
    home_pitcher_id: int = None
    away_pitcher:   str = ""
    away_pitcher_id: int = None
    # Lineups (filled when confirmed)
    home_lineup:    list = field(default_factory=list)
    away_lineup:    list = field(default_factory=list)
    lineups_confirmed: bool = False


class MLBClient:
    """MLB Stats API client — free, no auth."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get(self, endpoint: str, params: dict = None):
        try:
            resp = self.session.get(f"{BASE}/{endpoint}",
                                    params=params or {}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[MLB] API error on {endpoint}: {e}")
            return None

    def get_todays_games(self, date_str: str = None) -> list[MLBGame]:
        """
        Get today's games with probable pitchers and venue.
        date_str format: YYYY-MM-DD (defaults to today)
        """
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")

        data = self._get("schedule", {
            "sportId": 1,
            "date": date_str,
            "hydrate": "probablePitcher,venue,team",
        })
        if not data:
            return []

        games = []
        for date_block in data.get("dates", []):
            for g in date_block.get("games", []):
                teams = g.get("teams", {})
                home = teams.get("home", {})
                away = teams.get("away", {})
                venue = g.get("venue", {})

                home_pitcher = home.get("probablePitcher", {})
                away_pitcher = away.get("probablePitcher", {})

                games.append(MLBGame(
                    game_pk=g.get("gamePk"),
                    away_team=away.get("team", {}).get("name", ""),
                    home_team=home.get("team", {}).get("name", ""),
                    game_time=g.get("gameDate", ""),
                    status=g.get("status", {}).get("detailedState", ""),
                    venue=venue.get("name", ""),
                    venue_id=venue.get("id"),
                    home_pitcher=home_pitcher.get("fullName", ""),
                    home_pitcher_id=home_pitcher.get("id"),
                    away_pitcher=away_pitcher.get("fullName", ""),
                    away_pitcher_id=away_pitcher.get("id"),
                ))

        logger.info(f"[MLB] {len(games)} games on {date_str}")
        return games

    def classify_status(self, status: str) -> str:
        """
        Classify a game's detailed status into: upcoming / live / final.
        """
        status_lower = (status or "").lower()
        if any(w in status_lower for w in
               ["final", "completed", "game over", "postponed", "suspended"]):
            return "final"
        if any(w in status_lower for w in
               ["in progress", "live", "delayed", "warmup", "manager challenge"]):
            return "live"
        # Scheduled, Pre-Game, Preview, etc.
        return "upcoming"

    def get_lineup(self, game_pk: int) -> dict:
        """
        Get confirmed lineups for a game.
        Returns {'home': [players], 'away': [players], 'confirmed': bool}
        Lineups typically post 1-3 hours before first pitch.
        """
        data = self._get(f"../v1/game/{game_pk}/boxscore")
        if not data:
            return {"home": [], "away": [], "confirmed": False}

        result = {"home": [], "away": [], "confirmed": False}

        for side in ["home", "away"]:
            team_data = data.get("teams", {}).get(side, {})
            batting_order = team_data.get("battingOrder", [])
            players = team_data.get("players", {})

            lineup = []
            for player_id in batting_order:
                pkey = f"ID{player_id}"
                pdata = players.get(pkey, {})
                person = pdata.get("person", {})
                position = pdata.get("position", {})
                lineup.append({
                    "name": person.get("fullName", ""),
                    "id": person.get("id"),
                    "position": position.get("abbreviation", ""),
                    "batting_order": pdata.get("battingOrder", ""),
                })
            result[side] = lineup

        # Lineups confirmed if both sides have 9 batters
        result["confirmed"] = len(result["home"]) >= 9 and len(result["away"]) >= 9
        return result

    def get_injuries(self, team_id: int = None) -> list[dict]:
        """
        Get current injury list. If team_id given, filter to that team.
        """
        data = self._get("../v1/injuries") if False else None
        # MLB injuries endpoint via transactions
        data = self._get("transactions", {
            "startDate": datetime.now().strftime("%Y-%m-%d"),
            "endDate": datetime.now().strftime("%Y-%m-%d"),
        })
        injuries = []
        if data:
            for txn in data.get("transactions", []):
                if "inj" in txn.get("typeDesc", "").lower() or \
                   "IL" in txn.get("description", ""):
                    injuries.append({
                        "player": txn.get("person", {}).get("fullName", ""),
                        "team": txn.get("team", {}).get("name", ""),
                        "description": txn.get("description", ""),
                        "date": txn.get("date", ""),
                    })
        return injuries

    def get_pitcher_stats(self, pitcher_id: int) -> dict:
        """Get a pitcher's season stats + recent form."""
        if not pitcher_id:
            return {}
        data = self._get(f"../v1/people/{pitcher_id}", {
            "hydrate": "stats(group=[pitching],type=[season,statsSingleSeason])",
        })
        if not data:
            return {}

        people = data.get("people", [])
        if not people:
            return {}

        person = people[0]
        stats = person.get("stats", [])
        season_stats = {}
        for stat_group in stats:
            for split in stat_group.get("splits", []):
                s = split.get("stat", {})
                season_stats = {
                    "era": s.get("era"),
                    "whip": s.get("whip"),
                    "strikeouts": s.get("strikeOuts"),
                    "innings": s.get("inningsPitched"),
                    "wins": s.get("wins"),
                    "losses": s.get("losses"),
                    "k_per_9": s.get("strikeoutsPer9Inn"),
                }
        return {
            "name": person.get("fullName", ""),
            "throws": person.get("pitchHand", {}).get("code", ""),
            **season_stats,
        }

    def build_game_context(self, game: MLBGame) -> str:
        """
        Build a full text context for a game — for AI analysis.
        Includes pitchers, lineups (if confirmed), venue.
        """
        lines = [
            f"=== {game.away_team} @ {game.home_team} ===",
            f"Venue: {game.venue}",
            f"Status: {game.status}",
            "",
            "PROBABLE PITCHERS:",
        ]

        # Pitcher details
        for label, pid, pname in [
            (game.away_team, game.away_pitcher_id, game.away_pitcher),
            (game.home_team, game.home_pitcher_id, game.home_pitcher),
        ]:
            if pid:
                pstats = self.get_pitcher_stats(pid)
                if pstats:
                    lines.append(
                        f"  {label}: {pname} ({pstats.get('throws','?')}HP) — "
                        f"ERA {pstats.get('era','?')}, "
                        f"WHIP {pstats.get('whip','?')}, "
                        f"{pstats.get('k_per_9','?')} K/9"
                    )
                else:
                    lines.append(f"  {label}: {pname}")
            else:
                lines.append(f"  {label}: TBD")

        # Lineups
        lineup = self.get_lineup(game.game_pk)
        if lineup["confirmed"]:
            lines.append("\nCONFIRMED LINEUPS:")
            for side, team in [("away", game.away_team), ("home", game.home_team)]:
                lines.append(f"  {team}:")
                for p in lineup[side]:
                    lines.append(f"    {p['batting_order']}. {p['name']} ({p['position']})")
        else:
            lines.append("\nLINEUPS: Not yet confirmed (post 1-3 hrs before game)")

        return "\n".join(lines)
