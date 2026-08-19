"""
data_ingestion/official/schedule_engine.py

Automatically builds complete game context from OddsAPI data.
Answers: who plays next, when, probable pitchers, bullpen status,
recent results, and flags anything that needs manual verification.

No ESPN needed — uses OddsAPI (which we already have) as the
schedule source, then enriches with our news database.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from datetime import datetime, timedelta, timezone
from loguru import logger
from database.models import (
    get_session, Game, Team, GameOdds, NewsArticle, SocialPost
)
from config.settings import ODDS_API_KEY, ODDS_API_SPORT_KEYS

# OddsAPI endpoints
BASE_ODDS = "https://api.the-odds-api.com/v4"


class ScheduleEngine:
    """
    Pulls complete schedule data from OddsAPI and enriches with
    news/context to automatically answer betting-critical questions.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"
        })

    def _get(self, endpoint: str, params: dict = None) -> list | dict | None:
        """Make OddsAPI request."""
        params = params or {}
        params["apiKey"] = ODDS_API_KEY
        try:
            resp = self.session.get(
                f"{BASE_ODDS}/{endpoint}",
                params=params,
                timeout=15
            )
            remaining = resp.headers.get("x-requests-remaining", "?")
            logger.debug(f"[Schedule] OddsAPI credits remaining: {remaining}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[Schedule] OddsAPI error: {e}")
            return None

    def fetch_upcoming_games(self, sport: str) -> list[dict]:
        """
        Pull all upcoming scheduled games for a sport from OddsAPI.
        Returns enriched game dicts with team names, times, and odds.
        """
        sport_key = ODDS_API_SPORT_KEYS.get(sport)
        if not sport_key:
            return []

        # Get odds (includes game schedule as a side effect)
        data = self._get(
            f"sports/{sport_key}/odds",
            params={
                "regions": "us",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
            }
        )
        if not data:
            return []

        games = []
        for event in data:
            commence_utc = event.get("commence_time", "")
            try:
                game_dt = datetime.fromisoformat(
                    commence_utc.replace("Z", "+00:00")
                )
                # Convert to ET
                et_offset = timedelta(hours=-4)  # EDT
                game_dt_et = game_dt + et_offset
            except Exception:
                game_dt_et = None

            # Get best odds
            best_spread = best_total = best_home_ml = best_away_ml = None
            for bookmaker in event.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    outcomes = {o["name"]: o for o in market.get("outcomes", [])}
                    if market["key"] == "spreads" and best_spread is None:
                        home_o = outcomes.get(event.get("home_team", ""), {})
                        best_spread = home_o.get("point")
                    elif market["key"] == "totals" and best_total is None:
                        over_o = outcomes.get("Over", {})
                        best_total = over_o.get("point")
                    elif market["key"] == "h2h" and best_home_ml is None:
                        home_o = outcomes.get(event.get("home_team", ""), {})
                        away_o = outcomes.get(event.get("away_team", ""), {})
                        best_home_ml = home_o.get("price")
                        best_away_ml = away_o.get("price")

            games.append({
                "game_id":      f"{sport}_{event.get('id', '')}",
                "sport":        sport,
                "home_team":    event.get("home_team", ""),
                "away_team":    event.get("away_team", ""),
                "commence_utc": commence_utc,
                "game_time_et": game_dt_et.strftime("%a %b %d %I:%M %p ET")
                                if game_dt_et else "Unknown",
                "game_dt":      game_dt_et,
                "spread":       best_spread,
                "total":        best_total,
                "home_ml":      best_home_ml,
                "away_ml":      best_away_ml,
                "num_books":    len(event.get("bookmakers", [])),
            })

        # Sort by game time
        games.sort(key=lambda x: x.get("commence_utc", ""))
        logger.info(f"[Schedule] Fetched {len(games)} upcoming {sport} games.")
        return games

    def save_games_from_odds(self, sport: str):
        """
        Save game schedule to DB using OddsAPI as the source.
        This bypasses ESPN entirely for schedule data.
        """
        db = get_session()
        try:
            games = self.fetch_upcoming_games(sport)
            saved = updated = 0

            for g in games:
                existing = db.query(Game).filter_by(
                    game_id=g["game_id"]
                ).first()

                # Find team IDs in DB
                home_team = db.query(Team).filter(
                    Team.sport == sport,
                    Team.name.ilike(f"%{g['home_team'].split()[-1]}%")
                ).first()
                away_team = db.query(Team).filter(
                    Team.sport == sport,
                    Team.name.ilike(f"%{g['away_team'].split()[-1]}%")
                ).first()

                game_data = {
                    "sport":        sport,
                    "game_id":      g["game_id"],
                    "home_team_id": home_team.team_id if home_team else f"{sport}_unknown",
                    "away_team_id": away_team.team_id if away_team else f"{sport}_unknown",
                    "game_date":    g["game_dt"] or datetime.utcnow(),
                    "season_year":  datetime.utcnow().year,
                    "season_type":  "Regular",
                    "status":       "Scheduled",
                }

                if existing:
                    for k, v in game_data.items():
                        setattr(existing, k, v)
                    updated += 1
                else:
                    db.add(Game(**game_data))
                    saved += 1

                # Also save the odds
                if g.get("spread") or g.get("total"):
                    odds = GameOdds(
                        game_id=g["game_id"],
                        sport=sport,
                        sportsbook="best_available",
                        spread=g.get("spread"),
                        total_over_under=g.get("total"),
                        home_moneyline=g.get("home_ml"),
                        away_moneyline=g.get("away_ml"),
                        opening_spread=g.get("spread"),
                        opening_total=g.get("total"),
                        captured_at=datetime.utcnow(),
                    )
                    db.add(odds)

            db.commit()
            logger.info(f"[Schedule] ✅ {sport}: {saved} new games, "
                       f"{updated} updated.")
        except Exception as e:
            db.rollback()
            logger.error(f"[Schedule] Failed to save {sport} games: {e}")
        finally:
            db.close()

    def get_team_next_game(self, team_name: str, sport: str) -> dict | None:
        """
        Find the next scheduled game for a team.
        Answers: 'Who do the Mariners play next and when?'
        """
        games = self.fetch_upcoming_games(sport)
        now_utc = datetime.now(timezone.utc).isoformat()

        for game in games:
            if (team_name.lower() in game["home_team"].lower() or
                    team_name.lower() in game["away_team"].lower()):
                if game["commence_utc"] >= now_utc:
                    return game
        return None

    def get_todays_games(self, sport: str) -> list[dict]:
        """Get all games happening today."""
        games = self.fetch_upcoming_games(sport)
        today = datetime.now(timezone.utc).date()
        todays = []
        for g in games:
            try:
                game_date = datetime.fromisoformat(
                    g["commence_utc"].replace("Z", "+00:00")
                ).date()
                if game_date == today:
                    todays.append(g)
            except Exception:
                pass
        return todays

    def get_team_recent_results(self, team_name: str, sport: str,
                                n: int = 5) -> list[dict]:
        """
        Get a team's last N game results from OddsAPI scores endpoint.
        """
        sport_key = ODDS_API_SPORT_KEYS.get(sport)
        if not sport_key:
            return []

        data = self._get(
            f"sports/{sport_key}/scores/",
            params={"daysFrom": 7}
        )
        if not data:
            return []

        results = []
        for event in data:
            home = event.get("home_team", "")
            away = event.get("away_team", "")
            if (team_name.lower() in home.lower() or
                    team_name.lower() in away.lower()):
                if event.get("completed"):
                    scores = {s["name"]: s["score"]
                             for s in (event.get("scores") or [])}
                    results.append({
                        "date":      event.get("commence_time", "")[:10],
                        "home":      home,
                        "away":      away,
                        "home_score": scores.get(home, "?"),
                        "away_score": scores.get(away, "?"),
                        "winner":    home if int(scores.get(home, 0) or 0) >
                                            int(scores.get(away, 0) or 0)
                                    else away,
                    })
        return results[-n:]

    def get_news_for_team(self, team_name: str, sport: str,
                          hours: int = 48) -> list:
        """Pull recent news mentioning a team."""
        db = get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            articles = (db.query(NewsArticle)
                       .filter(NewsArticle.sport == sport,
                               NewsArticle.published_at >= cutoff)
                       .order_by(NewsArticle.published_at.desc())
                       .all())
            # Filter to articles mentioning the team
            team_word = team_name.split()[-1]  # e.g. "Mariners" from "Seattle Mariners"
            relevant = [a for a in articles
                       if team_word.lower() in (a.title or "").lower() or
                          team_word.lower() in (a.content or "").lower()]
            return relevant[:10]
        finally:
            db.close()

    def build_game_brief(self, home_team: str, away_team: str,
                         sport: str) -> str:
        """
        Build a complete automatic game brief — the answer to
        'what do we need to know about this game before betting?'
        """
        games = self.fetch_upcoming_games(sport)

        # Find this specific game
        game = None
        for g in games:
            if (home_team.lower() in g["home_team"].lower() and
                    away_team.lower() in g["away_team"].lower()):
                game = g
                break

        if not game:
            return f"Could not find upcoming game: {away_team} @ {home_team}"

        # Get news for both teams
        home_news = self.get_news_for_team(home_team, sport)
        away_news = self.get_news_for_team(away_team, sport)

        # Get recent results
        home_results = self.get_team_recent_results(home_team, sport)
        away_results = self.get_team_recent_results(away_team, sport)

        # Build brief
        lines = [
            f"GAME BRIEF: {game['away_team']} @ {game['home_team']}",
            f"Time: {game['game_time_et']}",
            f"Sport: {sport}",
            "",
            "BETTING LINES:",
            "  Spread: " + (f"{game['spread']:+.1f}" if game.get('spread') else 'Not available'),
            "  Total: " + str(game['total'] or 'Not available'),
            "  Home ML: " + (f"{game['home_ml']:+d}" if game.get('home_ml') else 'Not available'),
            "  Away ML: " + (f"{game['away_ml']:+d}" if game.get('away_ml') else 'Not available'),
            f"  Books: {game['num_books']} sportsbooks tracked",
            "",
        ]

        # Away team recent results
        if away_results:
            lines.append(f"RECENT RESULTS — {game['away_team']}:")
            for r in away_results:
                result_str = (f"  {r['date']}: {r['away']} @ {r['home']} — "
                             f"{r['away_score']}-{r['home_score']}")
                lines.append(result_str)
        else:
            lines.append(f"RECENT RESULTS — {game['away_team']}: Not available")

        lines.append("")

        # Home team recent results
        if home_results:
            lines.append(f"RECENT RESULTS — {game['home_team']}:")
            for r in home_results:
                result_str = (f"  {r['date']}: {r['away']} @ {r['home']} — "
                             f"{r['away_score']}-{r['home_score']}")
                lines.append(result_str)
        else:
            lines.append(f"RECENT RESULTS — {game['home_team']}: Not available")

        lines.append("")

        # News
        all_news = away_news + home_news
        if all_news:
            lines.append("RELEVANT NEWS (last 48hrs):")
            for a in all_news[:8]:
                impact_flag = "🚨" if a.betting_impact == "high" else "📰"
                lines.append(f"  {impact_flag} [{a.source}] {a.title}")
        else:
            lines.append("RELEVANT NEWS: None found in database")

        lines.append("")
        lines.append("DATA GAPS (verify before betting):")

        gaps = []
        if not home_results:
            gaps.append(f"Recent results for {home_team} — check manually")
        if not away_results:
            gaps.append(f"Recent results for {away_team} — check manually")
        if not all_news:
            gaps.append("No news found — check injury reports manually")
        if game["num_books"] < 3:
            gaps.append("Limited sportsbook coverage — line may not be sharp")

        for gap in gaps:
            lines.append(f"  ⚠️ {gap}")

        if not gaps:
            lines.append("  None — all key data available")

        return "\n".join(lines)

    def run_full_schedule_load(self):
        """Load schedule from OddsAPI for all sports — bypasses ESPN."""
        from config.settings import SUPPORTED_SPORTS
        for sport in SUPPORTED_SPORTS:
            logger.info(f"[Schedule] Loading {sport} schedule from OddsAPI...")
            self.save_games_from_odds(sport)
