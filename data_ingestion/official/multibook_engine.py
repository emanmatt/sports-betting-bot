"""
data_ingestion/official/multibook_engine.py

Pulls player props from ALL sportsbooks including alternate lines.
For each player+stat, shows:
  - Every book's line and odds
  - The BEST available number (highest over line / lowest under line)
  - The BEST odds at any given line
  - Alternate lines (same prop at 25.5, 27.5, 29.5, etc.)

This is the core of the line-shopping / Outlier-style comparison.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from datetime import datetime, timezone
from dataclasses import dataclass, field
from collections import defaultdict
from loguru import logger
from config.settings import ODDS_API_KEY, ODDS_API_SPORT_KEYS

BASE_ODDS = "https://api.the-odds-api.com/v4"

# All the books we want to track
TARGET_BOOKS = [
    "fanduel", "draftkings", "betmgm", "caesars",
    "pointsbetus", "betrivers", "espnbet", "fanatics",
    "hardrockbet", "bovada", "betonlineag",
]

# Main + alternate prop markets by sport
PROP_MARKETS = {
    "NBA": [
        "player_points", "player_points_alternate",
        "player_rebounds", "player_rebounds_alternate",
        "player_assists", "player_assists_alternate",
        "player_threes", "player_threes_alternate",
        "player_points_rebounds_assists",
    ],
    "NFL": [
        "player_pass_yds", "player_pass_yds_alternate",
        "player_rush_yds", "player_rush_yds_alternate",
        "player_reception_yds", "player_reception_yds_alternate",
        "player_receptions", "player_receptions_alternate",
        "player_pass_tds", "player_anytime_td",
    ],
    "MLB": [
        "batter_hits", "batter_hits_alternate",
        "batter_total_bases", "batter_total_bases_alternate",
        "batter_home_runs", "batter_rbis",
        "pitcher_strikeouts", "pitcher_strikeouts_alternate",
    ],
    "NHL": [
        "player_points", "player_points_alternate",
        "player_shots_on_goal", "player_shots_on_goal_alternate",
        "player_goals", "player_assists",
    ],
}


@dataclass
class BookLine:
    """One book's line for a prop."""
    sportsbook:  str
    line:        float
    over_odds:   int = None
    under_odds:  int = None


@dataclass
class MultiBookProp:
    """
    All lines for one player+stat across all books,
    including alternate lines.
    """
    player_name:   str
    game_id:       str
    sport:         str
    prop_type:     str          # normalized, e.g. "points"
    prop_label:    str
    home_team:     str = ""
    away_team:     str = ""
    # Main line (most common line across books)
    main_line:     float = None
    # Every book's main line
    book_lines:    list = field(default_factory=list)   # list[BookLine]
    # Alternate lines: {line_value: [BookLine, ...]}
    alt_lines:     dict = field(default_factory=dict)
    # Best available
    best_over_line: float = None
    best_over_odds: int = None
    best_over_book: str = ""
    best_under_line: float = None
    best_under_odds: int = None
    best_under_book: str = ""
    # Consensus (average line across books)
    consensus_line: float = None
    captured_at:    datetime = field(default_factory=datetime.utcnow)


class MultiBookEngine:
    """Pulls and organizes props across all books + alternate lines."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"
        })

    def _get(self, endpoint: str, params: dict = None):
        params = params or {}
        params["apiKey"] = ODDS_API_KEY
        try:
            resp = self.session.get(f"{BASE_ODDS}/{endpoint}",
                                    params=params, timeout=20)
            remaining = resp.headers.get("x-requests-remaining", "?")
            logger.debug(f"[MultiBook] Credits remaining: {remaining}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[MultiBook] API error: {e}")
            return None

    def _normalize_prop_type(self, market_key: str) -> tuple[str, str]:
        """Convert market key to (normalized_type, display_label)."""
        base = market_key.replace("_alternate", "")
        labels = {
            "player_points":         ("points", "Points"),
            "player_rebounds":       ("rebounds", "Rebounds"),
            "player_assists":        ("assists", "Assists"),
            "player_threes":         ("threes", "3-Pointers"),
            "player_pass_yds":       ("pass_yds", "Pass Yards"),
            "player_rush_yds":       ("rush_yds", "Rush Yards"),
            "player_reception_yds":  ("rec_yds", "Receiving Yards"),
            "player_receptions":     ("receptions", "Receptions"),
            "batter_hits":           ("hits", "Hits"),
            "batter_total_bases":    ("total_bases", "Total Bases"),
            "batter_home_runs":      ("home_runs", "Home Runs"),
            "pitcher_strikeouts":    ("strikeouts", "Strikeouts"),
            "player_shots_on_goal":  ("shots", "Shots on Goal"),
            "player_goals":          ("goals", "Goals"),
        }
        return labels.get(base, (base, base.replace("_", " ").title()))

    def _is_alternate(self, market_key: str) -> bool:
        return "_alternate" in market_key

    def fetch_multibook_props(self, sport: str) -> list[MultiBookProp]:
        """
        Fetch all props across all books including alternates.
        Groups by player+stat, organizes main vs alternate lines.
        """
        sport_key = ODDS_API_SPORT_KEYS.get(sport)
        if not sport_key:
            return []

        markets = PROP_MARKETS.get(sport, [])
        if not markets:
            return []

        # Get today's events
        events = self._get(f"sports/{sport_key}/events")
        if not events:
            return []

        today = datetime.now(timezone.utc).date()
        todays_events = []
        for e in events:
            try:
                d = datetime.fromisoformat(
                    e["commence_time"].replace("Z", "+00:00")
                ).date()
                if d == today:
                    todays_events.append(e)
            except Exception:
                pass

        logger.info(f"[MultiBook] {len(todays_events)} {sport} games today.")

        # Accumulator: key = (player, prop_type, game_id)
        # value = {"main": {book: BookLine}, "alt": {line: {book: BookLine}}}
        accumulator = defaultdict(lambda: {
            "main": {}, "alt": defaultdict(dict), "meta": {}
        })

        for event in todays_events[:5]:  # Cap to save credits
            event_id = event.get("id", "")
            game_id = f"{sport}_{event_id}"
            home = event.get("home_team", "")
            away = event.get("away_team", "")

            data = self._get(
                f"sports/{sport_key}/events/{event_id}/odds",
                params={
                    "regions": "us",
                    "markets": ",".join(markets),
                    "oddsFormat": "american",
                    "bookmakers": ",".join(TARGET_BOOKS),
                }
            )
            if not data:
                continue

            for bookmaker in data.get("bookmakers", []):
                book = bookmaker.get("key", "")
                for market in bookmaker.get("markets", []):
                    mkey = market.get("key", "")
                    is_alt = self._is_alternate(mkey)
                    prop_type, prop_label = self._normalize_prop_type(mkey)

                    # Group outcomes by player
                    by_player = defaultdict(dict)
                    for outcome in market.get("outcomes", []):
                        player = outcome.get("description", "")
                        side = outcome.get("name", "").lower()
                        price = outcome.get("price")
                        point = outcome.get("point")
                        if not player or point is None:
                            continue
                        if "over" in side:
                            by_player[player]["line"] = point
                            by_player[player]["over"] = price
                        elif "under" in side:
                            by_player[player]["under"] = price

                    for player, vals in by_player.items():
                        key = (player, prop_type, game_id)
                        accumulator[key]["meta"] = {
                            "player": player, "prop_type": prop_type,
                            "prop_label": prop_label, "game_id": game_id,
                            "sport": sport, "home": home, "away": away,
                        }
                        line = BookLine(
                            sportsbook=book,
                            line=vals.get("line"),
                            over_odds=vals.get("over"),
                            under_odds=vals.get("under"),
                        )
                        if is_alt:
                            accumulator[key]["alt"][vals["line"]][book] = line
                        else:
                            accumulator[key]["main"][book] = line

        # Build MultiBookProp objects
        results = []
        for key, data in accumulator.items():
            if not data["main"] and not data["alt"]:
                continue
            meta = data["meta"]

            main_lines = list(data["main"].values())

            # Consensus = most common main line
            consensus = None
            if main_lines:
                line_vals = [bl.line for bl in main_lines if bl.line is not None]
                if line_vals:
                    consensus = round(sum(line_vals) / len(line_vals), 1)

            # Best over = highest line (with valid over odds)
            best_over = best_under = None
            over_candidates = [bl for bl in main_lines if bl.over_odds is not None]
            under_candidates = [bl for bl in main_lines if bl.under_odds is not None]

            if over_candidates:
                # Best over value: higher line is better for over bettor,
                # but also want good odds. Prioritize line, then odds.
                best_over = max(over_candidates,
                               key=lambda x: (x.line, x.over_odds or -1000))
            if under_candidates:
                best_under = min(under_candidates,
                                key=lambda x: (x.line, -(x.under_odds or -1000)))

            prop = MultiBookProp(
                player_name=meta["player"],
                game_id=meta["game_id"],
                sport=meta["sport"],
                prop_type=meta["prop_type"],
                prop_label=meta["prop_label"],
                home_team=meta["home"],
                away_team=meta["away"],
                main_line=consensus,
                consensus_line=consensus,
                book_lines=main_lines,
                alt_lines={
                    line_val: list(books.values())
                    for line_val, books in data["alt"].items()
                },
                best_over_line=best_over.line if best_over else None,
                best_over_odds=best_over.over_odds if best_over else None,
                best_over_book=best_over.sportsbook if best_over else "",
                best_under_line=best_under.line if best_under else None,
                best_under_odds=best_under.under_odds if best_under else None,
                best_under_book=best_under.sportsbook if best_under else "",
            )
            results.append(prop)

        logger.info(f"[MultiBook] Built {len(results)} multi-book props for {sport}.")
        return results

    def get_line_shopping_summary(self, prop: MultiBookProp) -> dict:
        """
        Summarize the line-shopping value for a prop.
        Shows how much edge exists from shopping the best number.
        """
        if not prop.book_lines:
            return {}

        lines = [bl.line for bl in prop.book_lines if bl.line is not None]
        over_odds = [bl.over_odds for bl in prop.book_lines if bl.over_odds is not None]
        under_odds = [bl.under_odds for bl in prop.book_lines if bl.under_odds is not None]

        return {
            "num_books":       len(prop.book_lines),
            "line_range":      (min(lines), max(lines)) if lines else (None, None),
            "line_spread":     round(max(lines) - min(lines), 1) if lines else 0,
            "best_over_odds":  max(over_odds) if over_odds else None,
            "worst_over_odds": min(over_odds) if over_odds else None,
            "num_alt_lines":   len(prop.alt_lines),
            "has_shopping_edge": (max(lines) - min(lines) >= 0.5) if lines else False,
        }
