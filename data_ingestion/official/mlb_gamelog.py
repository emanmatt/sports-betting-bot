"""
data_ingestion/official/mlb_gamelog.py

Backfills player game-by-game stats from the MLB Stats API into
the PlayerStats table. This is what makes L10 hit rates and
projections actually work.

Pulls last ~20 games per player for:
  - Batters: hits, home runs, RBIs, total bases, runs
  - Pitchers: strikeouts, innings, earned runs

MLB Stats API is free, no key needed.
Run this once to backfill, then the scheduler keeps it current.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
import time
from datetime import datetime
from loguru import logger
from database.models import get_session, Player, PlayerStats, Game

BASE = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"}
SEASON = datetime.now().year


class MLBGameLogBackfill:
    """Pulls player game logs from MLB Stats API into the database."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.db = get_session()

    def close(self):
        self.db.close()

    def _get(self, endpoint: str, params: dict = None):
        try:
            resp = self.session.get(f"{BASE}/{endpoint}",
                                    params=params or {}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"[GameLog] API error: {e}")
            return None

    def get_active_players(self) -> list[dict]:
        """Get all active MLB players on 40-man rosters."""
        teams_data = self._get("teams", {"sportId": 1, "activeStatus": "Y"})
        if not teams_data:
            return []

        players = []
        for team in teams_data.get("teams", []):
            team_id = team.get("id")
            roster = self._get(f"../v1/teams/{team_id}/roster",
                              {"rosterType": "active"})
            if not roster:
                continue
            for entry in roster.get("roster", []):
                person = entry.get("person", {})
                position = entry.get("position", {})
                players.append({
                    "id": person.get("id"),
                    "name": person.get("fullName", ""),
                    "team_id": team_id,
                    "team": team.get("name", ""),
                    "position": position.get("abbreviation", ""),
                    "is_pitcher": position.get("abbreviation") in ["P", "SP", "RP"],
                })
            time.sleep(0.3)  # Rate limit politeness
        logger.info(f"[GameLog] Found {len(players)} active players.")
        return players

    def get_player_gamelog(self, player_id: int,
                           is_pitcher: bool) -> list[dict]:
        """Get a player's game-by-game log for this season."""
        group = "pitching" if is_pitcher else "hitting"
        data = self._get(f"../v1/people/{player_id}/stats", {
            "stats": "gameLog",
            "season": SEASON,
            "group": group,
        })
        if not data:
            return []

        games = []
        for stat_group in data.get("stats", []):
            for split in stat_group.get("splits", []):
                stat = split.get("stat", {})
                game = split.get("game", {})
                date = split.get("date", "")

                if is_pitcher:
                    games.append({
                        "game_pk": game.get("gamePk"),
                        "date": date,
                        "strikeouts": stat.get("strikeOuts", 0),
                        "innings": float(stat.get("inningsPitched", 0) or 0),
                        "earned_runs": stat.get("earnedRuns", 0),
                        "hits_allowed": stat.get("hits", 0),
                    })
                else:
                    hits = stat.get("hits", 0)
                    doubles = stat.get("doubles", 0)
                    triples = stat.get("triples", 0)
                    hrs = stat.get("homeRuns", 0)
                    # Total bases = singles + 2*doubles + 3*triples + 4*HR
                    singles = hits - doubles - triples - hrs
                    total_bases = singles + 2*doubles + 3*triples + 4*hrs
                    games.append({
                        "game_pk": game.get("gamePk"),
                        "date": date,
                        "hits": hits,
                        "home_runs": hrs,
                        "rbi": stat.get("rbi", 0),
                        "total_bases": total_bases,
                        "runs": stat.get("runs", 0),
                    })
        return games

    def save_player_gamelog(self, player_info: dict) -> int:
        """Fetch and save a player's game log. Returns games saved."""
        player_id = player_info["id"]
        is_pitcher = player_info["is_pitcher"]

        # Ensure player exists in our DB
        db_player = self.db.query(Player).filter_by(
            player_id=str(player_id)
        ).first()
        if not db_player:
            db_player = Player(
                player_id=str(player_id),
                full_name=player_info["name"],
                sport="MLB",
                position=player_info["position"],
                team_id=str(player_info["team_id"]),
                injury_status="Active",
            )
            self.db.add(db_player)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()

        games = self.get_player_gamelog(player_id, is_pitcher)
        saved = 0

        for g in games[-20:]:  # Last 20 games
            game_key = f"MLBLOG_{player_id}_{g['game_pk']}"

            # Check if already saved
            existing = self.db.query(PlayerStats).filter_by(
                player_id=str(player_id), game_id=game_key
            ).first()
            if existing:
                continue

            try:
                stat = PlayerStats(
                    player_id=str(player_id),
                    game_id=game_key,
                    sport="MLB",
                    season_year=SEASON,
                    raw_stats=g,
                )
                if is_pitcher:
                    stat.strikeouts = int(g.get("strikeouts", 0) or 0)
                else:
                    stat.hits = int(g.get("hits", 0) or 0)
                    stat.home_runs = int(g.get("home_runs", 0) or 0)
                    stat.rbi = int(g.get("rbi", 0) or 0)

                self.db.add(stat)
                self.db.commit()
                saved += 1
            except Exception as e:
                self.db.rollback()
                logger.debug(f"[GameLog] Skip {player_info['name']} game: {e}")
                continue

        return saved

    def run_backfill(self, limit: int = None):
        """
        Full backfill of all active players' game logs.
        limit: optionally cap number of players (for testing).
        """
        logger.info("=" * 60)
        logger.info("  MLB GAME LOG BACKFILL")
        logger.info("=" * 60)

        players = self.get_active_players()
        if limit:
            players = players[:limit]

        total_games = 0
        for i, player in enumerate(players):
            saved = self.save_player_gamelog(player)
            total_games += saved
            if (i + 1) % 25 == 0:
                logger.info(f"[GameLog] {i+1}/{len(players)} players, "
                           f"{total_games} game logs saved...")
            time.sleep(0.2)  # Be polite to MLB API

        logger.info(f"[GameLog] ✅ Complete: {total_games} game logs "
                   f"across {len(players)} players.")
        return total_games


if __name__ == "__main__":
    backfill = MLBGameLogBackfill()
    try:
        backfill.run_backfill()
    finally:
        backfill.close()
