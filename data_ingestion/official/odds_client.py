"""
data_ingestion/official/odds_client.py
Pulls live odds, spreads, totals, and moneylines from the-odds-api.com
Updates every 5 minutes to capture line movement.

Sign up for a free key at: https://the-odds-api.com
Free tier: 500 requests/month. Paid ($50/mo) = 150,000 requests/month.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from datetime import datetime
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
from database.models import get_session, Game, GameOdds
from config.settings import ODDS_API_KEY, ODDS_API_SPORT_KEYS, SUPPORTED_SPORTS

BASE_URL = "https://api.the-odds-api.com/v4"

# Sportsbooks to track (focus on major US books)
TARGET_BOOKS = [
    "draftkings", "fanduel", "betmgm", "caesars",
    "pointsbetus", "betonlineag", "bovada"
]


class OddsClient:
    """Fetches live betting lines from the-odds-api.com"""

    def __init__(self):
        if not ODDS_API_KEY:
            logger.warning("[Odds] No ODDS_API_KEY set. Add it to your .env file.")
        self.session = requests.Session()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _get(self, endpoint: str, params: dict = None) -> dict | list:
        params = params or {}
        params["apiKey"] = ODDS_API_KEY
        resp = self.session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)

        # Log remaining API quota
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        logger.debug(f"[Odds API] Quota: {remaining} remaining / {used} used")

        resp.raise_for_status()
        return resp.json()

    def fetch_odds_for_sport(self, sport: str) -> list[dict]:
        """
        Fetch current odds for all upcoming games in a sport.
        Returns list of parsed odds records ready for DB insert.
        """
        sport_key = ODDS_API_SPORT_KEYS.get(sport)
        if not sport_key:
            logger.warning(f"[Odds] Unknown sport: {sport}")
            return []

        try:
            data = self._get(
                f"sports/{sport_key}/odds",
                params={
                    "regions":  "us",
                    "markets":  "h2h,spreads,totals",  # moneyline, spread, over/under
                    "oddsFormat": "american",
                    "bookmakers": ",".join(TARGET_BOOKS),
                }
            )
        except Exception as e:
            logger.error(f"[Odds] Failed to fetch {sport} odds: {e}")
            return []

        odds_records = []
        for event in data:
            game_id = f"{sport}_{event.get('id', '')}"
            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")
            commence_time = event.get("commence_time", "")

            for bookmaker in event.get("bookmakers", []):
                book_key = bookmaker.get("key", "")
                if book_key not in TARGET_BOOKS:
                    continue

                # Parse each market
                record = {
                    "game_id":    game_id,
                    "sport":      sport,
                    "sportsbook": book_key,
                    "captured_at": datetime.utcnow(),
                }

                for market in bookmaker.get("markets", []):
                    mkey = market.get("key", "")
                    outcomes = {o["name"]: o for o in market.get("outcomes", [])}

                    if mkey == "h2h":  # Moneyline
                        home_outcome = outcomes.get(home_team, {})
                        away_outcome = outcomes.get(away_team, {})
                        record["home_moneyline"] = home_outcome.get("price")
                        record["away_moneyline"] = away_outcome.get("price")

                    elif mkey == "spreads":  # Point spread
                        home_outcome = outcomes.get(home_team, {})
                        away_outcome = outcomes.get(away_team, {})
                        record["spread"]      = home_outcome.get("point")
                        record["spread_juice"] = home_outcome.get("price")

                    elif mkey == "totals":  # Over/Under
                        over_outcome = outcomes.get("Over", {})
                        record["total_over_under"] = over_outcome.get("point")
                        record["total_juice"]      = over_outcome.get("price")

                odds_records.append(record)

        logger.info(f"[Odds] Fetched odds for {len(data)} {sport} events, "
                    f"{len(odds_records)} book records.")
        return odds_records

    def detect_line_movement(self, game_id: str, sport: str, sportsbook: str,
                              new_spread: float, new_total: float) -> dict:
        """
        Compare new odds against the most recent saved odds.
        Returns movement info and sharp money signal.
        """
        db = get_session()
        try:
            # Get the most recent saved odds for this game+book
            prev = (db.query(GameOdds)
                    .filter_by(game_id=game_id, sportsbook=sportsbook)
                    .order_by(GameOdds.captured_at.desc())
                    .first())

            if not prev:
                return {"is_new": True, "spread_moved": 0, "total_moved": 0}

            spread_moved = 0
            total_moved  = 0

            if prev.spread and new_spread:
                spread_moved = round(new_spread - prev.spread, 1)
            if prev.total_over_under and new_total:
                total_moved = round(new_total - prev.total_over_under, 1)

            # Sharp money signal: line moves against public betting direction
            # (simplified — full sharp detection needs public bet % data)
            sharp_signal = None
            if abs(spread_moved) >= 1.5:
                sharp_signal = "significant_move"
                logger.info(f"⚡ SHARP MOVE: {game_id} | {sportsbook} | "
                            f"Spread moved {spread_moved:+.1f} | Total moved {total_moved:+.1f}")

            return {
                "is_new":       False,
                "spread_moved": spread_moved,
                "total_moved":  total_moved,
                "sharp_signal": sharp_signal,
                "opening_spread": prev.opening_spread or prev.spread,
                "opening_total":  prev.opening_total or prev.total_over_under,
            }
        finally:
            db.close()

    def save_odds(self, sport: str):
        """Fetch and save odds for a sport, tracking line movement."""
        db = get_session()
        try:
            odds_data = self.fetch_odds_for_sport(sport)
            saved = 0
            movements = 0

            for od in odds_data:
                # Detect line movement before saving
                movement = self.detect_line_movement(
                    od["game_id"], sport, od["sportsbook"],
                    od.get("spread"), od.get("total_over_under")
                )

                # If new game, set opening line
                if movement.get("is_new"):
                    od["opening_spread"]  = od.get("spread")
                    od["opening_total"]   = od.get("total_over_under")
                    od["opening_home_ml"] = od.get("home_moneyline")
                else:
                    od["opening_spread"]  = movement.get("opening_spread")
                    od["opening_total"]   = movement.get("opening_total")

                if movement.get("sharp_signal"):
                    movements += 1

                # Always insert a new record (we keep history of all line movements)
                db.add(GameOdds(**od))
                saved += 1

            db.commit()
            logger.info(f"[Odds] ✅ Saved {saved} {sport} odds records. "
                        f"{movements} significant line moves detected.")
        except Exception as e:
            db.rollback()
            logger.error(f"[Odds] Failed to save {sport} odds: {e}")
        finally:
            db.close()

    def get_player_props(self, sport: str) -> list[dict]:
        """
        Fetch player prop lines (points, yards, strikeouts, etc.)
        These are key for player-specific bets.
        """
        sport_key = ODDS_API_SPORT_KEYS.get(sport)
        if not sport_key:
            return []

        # Prop markets vary by sport
        prop_markets = {
            "NBA": "player_points,player_rebounds,player_assists,player_threes",
            "NFL": "player_pass_yards,player_rush_yards,player_reception_yards,player_tds",
            "MLB": "batter_home_runs,batter_hits,pitcher_strikeouts",
            "NHL": "player_goals,player_shots_on_goal,player_assists",
        }

        market = prop_markets.get(sport, "")
        if not market:
            return []

        try:
            data = self._get(
                f"sports/{sport_key}/events",
                params={"markets": market, "oddsFormat": "american"}
            )
            logger.info(f"[Odds] Fetched {len(data)} {sport} prop markets.")
            return data
        except Exception as e:
            logger.error(f"[Odds] Player props failed for {sport}: {e}")
            return []

    def run_all_sports(self):
        """Update odds for all sports."""
        for sport in SUPPORTED_SPORTS:
            self.save_odds(sport)


if __name__ == "__main__":
    client = OddsClient()
    client.run_all_sports()
