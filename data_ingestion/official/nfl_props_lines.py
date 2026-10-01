"""
data_ingestion/official/nfl_props_lines.py

NFL real prop lines + alternate lines from OddsAPI, mirroring the MLB
PropsLines class but with NFL's sport key and markets. Kept separate so
MLB stays untouched.

OddsAPI NFL prop market keys (standard + alternate):
  player_pass_yds         / player_pass_yds_alternate
  player_pass_tds         / player_pass_tds_alternate
  player_rush_yds         / player_rush_yds_alternate
  player_reception_yds    / player_reception_yds_alternate
  player_receptions       / player_receptions_alternate
  player_anytime_td       (no alt)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from dataclasses import dataclass, field
from loguru import logger
from config.settings import ODDS_API_KEY

BASE_ODDS = "https://api.the-odds-api.com/v4"
NFL_KEY = "americanfootball_nfl"

STANDARD_MARKETS = [
    "player_pass_yds", "player_pass_tds", "player_rush_yds",
    "player_reception_yds", "player_receptions", "player_anytime_td",
]
ALT_MARKETS = [
    "player_pass_yds_alternate", "player_pass_tds_alternate",
    "player_rush_yds_alternate", "player_reception_yds_alternate",
    "player_receptions_alternate",
]

MARKET_LABELS = {
    "player_pass_yds": "Pass Yards",
    "player_pass_tds": "Pass TDs",
    "player_rush_yds": "Rush Yards",
    "player_reception_yds": "Rec Yards",
    "player_receptions": "Receptions",
    "player_anytime_td": "Anytime TD",
}
for k in list(MARKET_LABELS):
    if k != "player_anytime_td":
        MARKET_LABELS[k + "_alternate"] = MARKET_LABELS[k] + " (alt)"

TARGET_BOOKS = ["fanduel", "draftkings", "betmgm", "caesars"]


@dataclass
class LineOption:
    player_name: str
    market:      str
    label:       str
    line:        float
    over_odds:   int = None
    under_odds:  int = None
    book:        str = ""
    is_alt:      bool = False

    def implied_prob(self, side="over") -> float:
        odds = self.over_odds if side == "over" else self.under_odds
        if odds is None:
            return None
        if odds > 0:
            return round(100 / (odds + 100), 4)
        return round(-odds / (-odds + 100), 4)


@dataclass
class PlayerLines:
    player_name: str
    market:      str
    label:       str
    standard:    LineOption = None
    alternates:  list = field(default_factory=list)


class NFLPropsLines:
    """Fetches real NFL prop lines + alt lines, credit-economically."""

    def __init__(self):
        self.session = requests.Session()
        self._event_cache = {}
        self.last_credits = None

    def _get(self, endpoint, params=None):
        params = params or {}
        params["apiKey"] = ODDS_API_KEY
        r = self.session.get(f"{BASE_ODDS}/{endpoint}", params=params, timeout=20)
        self.last_credits = r.headers.get("x-requests-remaining")
        logger.debug(f"[NFLPropsLines] credits: {self.last_credits}")
        r.raise_for_status()
        return r.json()

    def get_events_today(self) -> list[dict]:
        try:
            return self._get(f"sports/{NFL_KEY}/events")
        except Exception as e:
            logger.error(f"[NFLPropsLines] events failed: {e}")
            return []

    def fetch_game_props(self, event_id: str, include_alt: bool = True) -> dict:
        cache_key = f"{event_id}_{include_alt}"
        if cache_key in self._event_cache:
            return self._event_cache[cache_key]
        markets = STANDARD_MARKETS + (ALT_MARKETS if include_alt else [])
        try:
            data = self._get(
                f"sports/{NFL_KEY}/events/{event_id}/odds",
                params={
                    "regions": "us",
                    "markets": ",".join(markets),
                    "oddsFormat": "american",
                    "bookmakers": ",".join(TARGET_BOOKS),
                }
            )
        except Exception as e:
            logger.error(f"[NFLPropsLines] props failed for {event_id}: {e}")
            return {}
        parsed = self._parse_event(data)
        self._event_cache[cache_key] = parsed
        return parsed

    def _parse_event(self, data: dict) -> dict:
        result = {}
        for book in data.get("bookmakers", []):
            book_key = book.get("key", "")
            for market in book.get("markets", []):
                mkey = market.get("key", "")
                base_market = mkey.replace("_alternate", "")
                is_alt = mkey.endswith("_alternate")
                by_player_line = {}
                for outcome in market.get("outcomes", []):
                    player = outcome.get("description", "")
                    point = outcome.get("point")
                    name = outcome.get("name", "")
                    price = outcome.get("price")
                    # anytime_td has no point — treat as line 0.5, Yes=over
                    if base_market == "player_anytime_td":
                        point = 0.5
                    if player is None or point is None:
                        continue
                    key = (player, point)
                    if key not in by_player_line:
                        by_player_line[key] = {"over": None, "under": None}
                    side = "over" if name.lower() in ("over", "yes") else "under"
                    by_player_line[key][side] = price

                for (player, point), sides in by_player_line.items():
                    opt = LineOption(
                        player_name=player, market=base_market,
                        label=MARKET_LABELS.get(base_market, base_market),
                        line=point, over_odds=sides.get("over"),
                        under_odds=sides.get("under"), book=book_key, is_alt=is_alt,
                    )
                    result.setdefault(player, {})
                    if base_market not in result[player]:
                        result[player][base_market] = PlayerLines(
                            player_name=player, market=base_market,
                            label=MARKET_LABELS.get(base_market, base_market),
                        )
                    pl = result[player][base_market]
                    if is_alt:
                        pl.alternates.append(opt)
                    elif pl.standard is None:
                        pl.standard = opt
        return result
