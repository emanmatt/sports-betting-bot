"""
data_ingestion/official/props_engine.py

Player props engine:
- Pulls live prop lines from OddsAPI for all sports
- Compares lines across all sportsbooks to find best number
- Checks player recent averages vs prop line
- Flags when prop line doesn't match player history
- Searches web for player matchup context automatically
- Saves edges to database for dashboard display
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger
from database.models import get_session, Player, PlayerStats, Game
from config.settings import ODDS_API_KEY, ODDS_API_SPORT_KEYS, ANTHROPIC_API_KEY

BASE_ODDS = "https://api.the-odds-api.com/v4"

# Prop markets per sport
PROP_MARKETS = {
    "NBA": [
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_points_rebounds_assists",
    ],
    "NFL": [
        "player_pass_yards",
        "player_pass_tds",
        "player_rush_yards",
        "player_reception_yards",
        "player_receptions",
    ],
    "MLB": [
        "batter_hits",
        "batter_total_bases",
        "batter_rbis",
        "pitcher_strikeouts",
        "pitcher_outs",
    ],
    "NHL": [
        "player_goals",
        "player_assists",
        "player_shots_on_goal",
        "player_points",
    ],
}

# Minimum edge threshold to flag a prop (in units)
MIN_EDGE_THRESHOLD = 0.5


@dataclass
class PropLine:
    """A single prop line from one sportsbook."""
    player_name:  str
    team:         str
    game_id:      str
    sport:        str
    prop_type:    str        # e.g. "player_points"
    prop_label:   str        # e.g. "Points"
    sportsbook:   str
    line:         float      # The over/under number
    over_odds:    int
    under_odds:   int
    captured_at:  datetime = field(default_factory=datetime.utcnow)


@dataclass
class PropEdge:
    """A flagged prop edge — line doesn't match player history."""
    player_name:      str
    team:             str
    opponent:         str
    game_id:          str
    sport:            str
    prop_type:        str
    prop_label:       str
    # Best lines across books
    best_over_line:   float
    best_over_odds:   int
    best_over_book:   str
    best_under_line:  float
    best_under_odds:  int
    best_under_book:  str
    # Line spread (difference between highest and lowest line)
    line_spread:      float
    # Player history
    player_avg:       Optional[float] = None   # Season average for this stat
    recent_avg:       Optional[float] = None   # Last 5 game average
    vs_opponent_avg:  Optional[float] = None   # Historical vs this opponent
    # Edge assessment
    edge_direction:   str = ""    # "over" / "under" / "none"
    edge_strength:    float = 0.0  # 0-10
    edge_reason:      str = ""
    # Web-searched context
    web_context:      str = ""
    # All lines for comparison
    all_lines:        list = field(default_factory=list)
    flagged_at:       datetime = field(default_factory=datetime.utcnow)


class PropsEngine:
    """Pulls and analyzes player props across all sports."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"
        })

    def _get(self, endpoint: str, params: dict = None) -> list | dict | None:
        params = params or {}
        params["apiKey"] = ODDS_API_KEY
        try:
            resp = self.session.get(
                f"{BASE_ODDS}/{endpoint}",
                params=params,
                timeout=20
            )
            remaining = resp.headers.get("x-requests-remaining", "?")
            logger.debug(f"[Props] OddsAPI credits: {remaining} remaining")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[Props] OddsAPI error: {e}")
            return None

    def fetch_props_for_sport(self, sport: str) -> list[PropLine]:
        """Pull all prop lines for a sport from OddsAPI."""
        sport_key = ODDS_API_SPORT_KEYS.get(sport)
        if not sport_key:
            return []

        markets = PROP_MARKETS.get(sport, [])
        if not markets:
            return []

        # OddsAPI requires fetching props per event
        # First get events
        events_data = self._get(f"sports/{sport_key}/events")
        if not events_data:
            return []

        all_props = []
        # Only fetch props for today's games to save API credits
        today = datetime.utcnow().date()
        todays_events = []
        for event in events_data:
            try:
                event_date = datetime.fromisoformat(
                    event["commence_time"].replace("Z", "+00:00")
                ).date()
                if event_date == today:
                    todays_events.append(event)
            except Exception:
                pass

        logger.info(f"[Props] Found {len(todays_events)} {sport} games today. "
                   f"Fetching props...")

        for event in todays_events[:6]:  # Cap to save credits
            event_id = event.get("id", "")
            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")

            # Fetch props for this event
            props_data = self._get(
                f"sports/{sport_key}/events/{event_id}/odds",
                params={
                    "regions":    "us",
                    "markets":    ",".join(markets[:3]),  # Top 3 markets
                    "oddsFormat": "american",
                }
            )
            if not props_data:
                continue

            game_id = f"{sport}_{event_id}"

            for bookmaker in props_data.get("bookmakers", []):
                book_key = bookmaker.get("key", "")
                for market in bookmaker.get("markets", []):
                    market_key = market.get("key", "")
                    prop_label = market_key.replace("player_", "").replace(
                        "_", " ").title()

                    # Group outcomes by player
                    player_outcomes = {}
                    for outcome in market.get("outcomes", []):
                        player = outcome.get("description", outcome.get("name", ""))
                        side = outcome.get("name", "").lower()  # "Over" or "Under"
                        price = outcome.get("price", 0)
                        point = outcome.get("point", 0)

                        if player not in player_outcomes:
                            player_outcomes[player] = {
                                "line": point,
                                "over_odds": None,
                                "under_odds": None,
                            }

                        if "over" in side:
                            player_outcomes[player]["over_odds"] = price
                            player_outcomes[player]["line"] = point
                        elif "under" in side:
                            player_outcomes[player]["under_odds"] = price

                    # Create PropLine for each player
                    for player_name, odds in player_outcomes.items():
                        if odds["line"] and odds["over_odds"] and odds["under_odds"]:
                            # Determine team
                            team = home_team  # Default, improve later
                            all_props.append(PropLine(
                                player_name=player_name,
                                team=team,
                                game_id=game_id,
                                sport=sport,
                                prop_type=market_key,
                                prop_label=prop_label,
                                sportsbook=book_key,
                                line=odds["line"],
                                over_odds=odds["over_odds"],
                                under_odds=odds["under_odds"],
                            ))

        logger.info(f"[Props] Fetched {len(all_props)} {sport} prop lines.")
        return all_props

    def find_best_lines(self, props: list[PropLine]) -> dict[str, dict]:
        """
        For each player+prop combination, find the best line
        across all sportsbooks.
        Returns dict keyed by "player_name|prop_type|game_id"
        """
        grouped = {}

        for prop in props:
            key = f"{prop.player_name}|{prop.prop_type}|{prop.game_id}"
            if key not in grouped:
                grouped[key] = {
                    "player_name": prop.player_name,
                    "team": prop.team,
                    "game_id": prop.game_id,
                    "sport": prop.sport,
                    "prop_type": prop.prop_type,
                    "prop_label": prop.prop_label,
                    "lines": [],
                }
            grouped[key]["lines"].append({
                "sportsbook": prop.sportsbook,
                "line": prop.line,
                "over_odds": prop.over_odds,
                "under_odds": prop.under_odds,
            })

        # Find best lines for each
        best = {}
        for key, data in grouped.items():
            lines = data["lines"]
            if not lines:
                continue

            # Best over = highest line number (more room for under)
            # Best under = lowest line number (easier to go under)
            # Best odds = closest to -110 (most value)
            best_over = max(lines, key=lambda x: (x["line"], -abs(x["over_odds"] + 110)))
            best_under = min(lines, key=lambda x: (x["line"], -abs(x["under_odds"] + 110)))

            line_values = [l["line"] for l in lines]
            line_spread = max(line_values) - min(line_values) if line_values else 0

            best[key] = {
                **data,
                "best_over_line":  best_over["line"],
                "best_over_odds":  best_over["over_odds"],
                "best_over_book":  best_over["sportsbook"],
                "best_under_line": best_under["line"],
                "best_under_odds": best_under["under_odds"],
                "best_under_book": best_under["sportsbook"],
                "line_spread":     line_spread,
                "all_lines":       lines,
                "num_books":       len(lines),
            }

        return best

    def get_player_stats_from_db(self, player_name: str,
                                  sport: str) -> dict:
        """Pull player's recent stats from our database."""
        db = get_session()
        try:
            player = (db.query(Player)
                     .filter(Player.sport == sport,
                             Player.full_name.ilike(f"%{player_name.split()[0]}%"))
                     .first())

            if not player:
                return {}

            # Get last 10 games
            recent = (db.query(PlayerStats)
                     .filter_by(player_id=player.player_id)
                     .order_by(PlayerStats.game_id.desc())
                     .limit(10)
                     .all())

            if not recent:
                return {}

            def safe_avg(vals):
                vals = [v for v in vals if v is not None]
                return round(sum(vals) / len(vals), 1) if vals else None

            return {
                "player_id":    player.player_id,
                "games_in_db":  len(recent),
                "pts_avg":      safe_avg([s.points for s in recent]),
                "reb_avg":      safe_avg([s.rebounds for s in recent]),
                "ast_avg":      safe_avg([s.assists for s in recent]),
                "pass_yds_avg": safe_avg([s.passing_yards for s in recent]),
                "rush_yds_avg": safe_avg([s.rushing_yards for s in recent]),
                "rec_yds_avg":  safe_avg([s.receiving_yards for s in recent]),
                "hits_avg":     safe_avg([s.hits for s in recent]),
                "k_avg":        safe_avg([s.strikeouts for s in recent]),
                "status":       player.injury_status or "Active",
            }
        finally:
            db.close()

    def assess_edge(self, prop_data: dict, player_stats: dict,
                    sport: str) -> tuple[str, float, str]:
        """
        Compare prop line to player history.
        Returns (direction, strength, reason)
        direction: "over" / "under" / "none"
        strength: 0-10
        """
        line = prop_data["best_over_line"]
        prop_type = prop_data["prop_type"]

        # Map prop type to stat
        stat_map = {
            "player_points":             player_stats.get("pts_avg"),
            "player_rebounds":           player_stats.get("reb_avg"),
            "player_assists":            player_stats.get("ast_avg"),
            "player_pass_yards":         player_stats.get("pass_yds_avg"),
            "player_rush_yards":         player_stats.get("rush_yds_avg"),
            "player_reception_yards":    player_stats.get("rec_yds_avg"),
            "batter_hits":               player_stats.get("hits_avg"),
            "pitcher_strikeouts":        player_stats.get("k_avg"),
        }

        player_avg = stat_map.get(prop_type)

        if player_avg is None:
            # No historical data — flag line spread as potential edge
            if prop_data.get("line_spread", 0) >= 1.0:
                return ("none", 3.0,
                        f"Line spread of {prop_data['line_spread']} across books — "
                        f"shop for best number")
            return "none", 0.0, "Insufficient player history"

        diff = player_avg - line
        pct_diff = abs(diff) / line if line else 0

        if diff > 0:
            direction = "over"
        elif diff < 0:
            direction = "under"
        else:
            return "none", 0.0, "Line matches historical average exactly"

        # Strength based on % difference
        if pct_diff >= 0.20:
            strength = 8.0
        elif pct_diff >= 0.15:
            strength = 6.5
        elif pct_diff >= 0.10:
            strength = 5.0
        elif pct_diff >= 0.05:
            strength = 3.5
        else:
            strength = 1.5

        # Boost strength if line spread is high (books disagree)
        if prop_data.get("line_spread", 0) >= 1.0:
            strength = min(10.0, strength + 1.0)

        reason = (f"Player avg {player_avg} vs line {line} "
                 f"({diff:+.1f}, {pct_diff:.0%} difference). "
                 f"Based on {player_stats.get('games_in_db', '?')} games in DB.")

        return direction, strength, reason

    def search_prop_context(self, player_name: str, team: str,
                            opponent: str, prop_type: str) -> str:
        """Auto-search for player matchup context."""
        if not ANTHROPIC_API_KEY:
            return ""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            prop_label = prop_type.replace("player_", "").replace("_", " ")

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                system="You are a sports betting researcher. Find specific, factual matchup data. Be concise.",
                messages=[{
                    "role": "user",
                    "content": (
                        f"For {player_name} ({team}) vs {opponent} today, find:\n"
                        f"1. Recent {prop_label} numbers (last 5 games)\n"
                        f"2. Historical {prop_label} vs {opponent}\n"
                        f"3. Any injury or lineup news affecting this prop\n"
                        f"Return only confirmed facts, 3-4 sentences max."
                    )
                }]
            )
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            return text.strip()[:400]
        except Exception as e:
            logger.debug(f"[Props] Web context search failed: {e}")
            return ""

    def analyze_props(self, sport: str,
                      search_web: bool = True) -> list[PropEdge]:
        """
        Full pipeline: fetch props, compare lines,
        check history, flag edges.
        """
        logger.info(f"[Props] Starting {sport} props analysis...")

        # Fetch all prop lines
        props = self.fetch_props_for_sport(sport)
        if not props:
            logger.info(f"[Props] No {sport} props available today.")
            return []

        # Find best lines across books
        best_lines = self.find_best_lines(props)
        logger.info(f"[Props] Found {len(best_lines)} unique {sport} props.")

        edges = []
        for key, prop_data in best_lines.items():
            player_name = prop_data["player_name"]
            sport_val = prop_data["sport"]

            # Get player history from DB
            player_stats = self.get_player_stats_from_db(player_name, sport_val)

            # Assess edge
            direction, strength, reason = self.assess_edge(
                prop_data, player_stats, sport_val
            )

            # Only keep meaningful edges
            if strength < MIN_EDGE_THRESHOLD:
                continue

            # Get opponent from game
            db = get_session()
            try:
                game = db.query(Game).filter_by(
                    game_id=prop_data["game_id"]
                ).first()
                opponent = ""
                if game:
                    from database.models import Team
                    opp_team = db.query(Team).filter_by(
                        team_id=game.away_team_id
                    ).first()
                    opponent = opp_team.name if opp_team else ""
            finally:
                db.close()

            # Web search for context on strong edges
            web_context = ""
            if search_web and strength >= 5.0:
                web_context = self.search_prop_context(
                    player_name, prop_data["team"],
                    opponent, prop_data["prop_type"]
                )

            edge = PropEdge(
                player_name=player_name,
                team=prop_data["team"],
                opponent=opponent,
                game_id=prop_data["game_id"],
                sport=sport_val,
                prop_type=prop_data["prop_type"],
                prop_label=prop_data["prop_label"],
                best_over_line=prop_data["best_over_line"],
                best_over_odds=prop_data["best_over_odds"],
                best_over_book=prop_data["best_over_book"],
                best_under_line=prop_data["best_under_line"],
                best_under_odds=prop_data["best_under_odds"],
                best_under_book=prop_data["best_under_book"],
                line_spread=prop_data.get("line_spread", 0),
                player_avg=player_stats.get("pts_avg") or player_stats.get("k_avg"),
                edge_direction=direction,
                edge_strength=strength,
                edge_reason=reason,
                web_context=web_context,
                all_lines=prop_data["all_lines"],
            )
            edges.append(edge)

        # Sort by edge strength
        edges.sort(key=lambda x: x.edge_strength, reverse=True)
        logger.info(f"[Props] ✅ {sport}: {len(edges)} prop edges identified.")
        return edges

    def run_all_sports(self) -> dict[str, list[PropEdge]]:
        """Run props analysis for all sports with games today."""
        from config.settings import SUPPORTED_SPORTS
        results = {}
        for sport in SUPPORTED_SPORTS:
            edges = self.analyze_props(sport, search_web=True)
            results[sport] = edges
        return results
