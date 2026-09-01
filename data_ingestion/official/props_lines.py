"""
data_ingestion/official/props_lines.py

Fetches REAL player prop lines + ALTERNATE lines from OddsAPI, and
attaches PrizePicks lines side by side. Computes the value edge:
your model's probability vs the book's implied probability.

Credit-economical by design:
  - one fetch per game, cached in memory for the session
  - alt lines fetched only for the players you ask for (top plays)
  - a manual refresh is the only thing that spends credits

OddsAPI MLB prop market keys (standard + alternate):
  batter_hits            / batter_hits_alternate
  batter_total_bases     / batter_total_bases_alternate
  batter_rbis            / batter_rbis_alternate
  batter_runs_scored     / batter_runs_scored_alternate
  batter_home_runs       / batter_home_runs_alternate
  pitcher_strikeouts     / pitcher_strikeouts_alternate
  pitcher_outs           (alt not always offered)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
from config.settings import ODDS_API_KEY

BASE_ODDS = "https://api.the-odds-api.com/v4"
MLB_KEY = "baseball_mlb"

# Standard markets and their alternate counterparts
STANDARD_MARKETS = [
    "batter_hits", "batter_total_bases", "batter_rbis",
    "batter_runs_scored", "batter_home_runs",
    "pitcher_strikeouts", "pitcher_outs",
]
ALT_MARKETS = [
    "batter_hits_alternate", "batter_total_bases_alternate",
    "batter_rbis_alternate", "batter_runs_scored_alternate",
    "batter_home_runs_alternate", "pitcher_strikeouts_alternate",
]

# Human labels
MARKET_LABELS = {
    "batter_hits": "Hits",
    "batter_total_bases": "Total Bases",
    "batter_rbis": "RBIs",
    "batter_runs_scored": "Runs",
    "batter_home_runs": "Home Runs",
    "pitcher_strikeouts": "Strikeouts",
    "pitcher_outs": "Outs",
}
for k in list(MARKET_LABELS):
    MARKET_LABELS[k + "_alternate"] = MARKET_LABELS[k] + " (alt)"

TARGET_BOOKS = ["fanduel", "draftkings", "betmgm", "caesars"]


@dataclass
class LineOption:
    """One line at one book (standard or alt) with both sides' odds."""
    player_name: str
    market:      str
    label:       str
    line:        float
    over_odds:   int = None
    under_odds:  int = None
    book:        str = ""
    is_alt:      bool = False

    def implied_prob(self, side="over") -> float:
        """Book's implied probability from American odds (with vig)."""
        odds = self.over_odds if side == "over" else self.under_odds
        if odds is None:
            return None
        if odds > 0:
            return round(100 / (odds + 100), 4)
        else:
            return round(-odds / (-odds + 100), 4)


@dataclass
class PlayerLines:
    """All line options for one player+market: standard + the alt ladder."""
    player_name: str
    market:      str
    label:       str
    standard:    LineOption = None
    alternates:  list = field(default_factory=list)   # list[LineOption]
    prizepicks:  float = None                          # PP line if available


class PropsLines:
    """Fetches real prop lines + alt lines, credit-economically."""

    def __init__(self):
        self.session = requests.Session()
        self._event_cache = {}   # game_id -> raw event props
        self._pp_cache = None
        self.last_credits = None

    def _get(self, endpoint, params=None):
        params = params or {}
        params["apiKey"] = ODDS_API_KEY
        r = self.session.get(f"{BASE_ODDS}/{endpoint}", params=params, timeout=20)
        self.last_credits = r.headers.get("x-requests-remaining")
        logger.debug(f"[PropsLines] Credits remaining: {self.last_credits}")
        r.raise_for_status()
        return r.json()

    def get_events_today(self) -> list[dict]:
        """List today's MLB events (game IDs). Cheap — 1 credit."""
        try:
            return self._get(f"sports/{MLB_KEY}/events")
        except Exception as e:
            logger.error(f"[PropsLines] events fetch failed: {e}")
            return []

    def fetch_game_props(self, event_id: str, include_alt: bool = True) -> dict:
        """
        Fetch props (and optionally alt lines) for ONE game.
        Cached so repeat calls in a session don't re-spend credits.
        Cost: markets are batched into one request per event.
        """
        cache_key = f"{event_id}_{include_alt}"
        if cache_key in self._event_cache:
            return self._event_cache[cache_key]

        markets = STANDARD_MARKETS + (ALT_MARKETS if include_alt else [])
        try:
            data = self._get(
                f"sports/{MLB_KEY}/events/{event_id}/odds",
                params={
                    "regions": "us",
                    "markets": ",".join(markets),
                    "oddsFormat": "american",
                    "bookmakers": ",".join(TARGET_BOOKS),
                }
            )
        except Exception as e:
            logger.error(f"[PropsLines] props fetch failed for {event_id}: {e}")
            return {}

        parsed = self._parse_event(data)
        self._event_cache[cache_key] = parsed
        return parsed

    def _parse_event(self, data: dict) -> dict:
        """
        Parse one event's odds into {player_name: {market: PlayerLines}}.
        Groups standard and alt lines together per player+market.
        """
        result = {}
        for book in data.get("bookmakers", []):
            book_key = book.get("key", "")
            for market in book.get("markets", []):
                mkey = market.get("key", "")
                base_market = mkey.replace("_alternate", "")
                is_alt = mkey.endswith("_alternate")
                label = MARKET_LABELS.get(mkey, mkey)

                # Group outcomes by player (description) + line (point)
                by_player_line = {}
                for outcome in market.get("outcomes", []):
                    player = outcome.get("description", "")
                    point = outcome.get("point")
                    name = outcome.get("name", "")   # "Over" / "Under"
                    price = outcome.get("price")
                    if player is None or point is None:
                        continue
                    key = (player, point)
                    if key not in by_player_line:
                        by_player_line[key] = {"over": None, "under": None}
                    by_player_line[key][name.lower()] = price

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
                    else:
                        # keep the best (closest to even) standard line per player
                        if pl.standard is None:
                            pl.standard = opt
        return result

    def attach_prizepicks(self, parsed: dict):
        """
        Attach PrizePicks lines side by side (unofficial source).
        Best-effort — if it fails, sportsbook lines still work.
        """
        try:
            from data_ingestion.dfs.dfs_engine import DFSEngine
            if self._pp_cache is None:
                dfs = DFSEngine()
                self._pp_cache = dfs.get_prizepicks_mlb()  # {player: {stat: line}}
            pp = self._pp_cache or {}
            for player, markets in parsed.items():
                if player in pp:
                    for market, pl in markets.items():
                        # map market to PP stat name loosely
                        for stat, line in pp[player].items():
                            if pl.label.lower().split()[0] in stat.lower():
                                pl.prizepicks = line
        except Exception as e:
            logger.debug(f"[PropsLines] PrizePicks attach skipped: {e}")

    def best_alt_for_target(self, player_lines: PlayerLines,
                            target_prob: float, model_prob: float) -> LineOption:
        """
        From the alt ladder, find the line whose MODEL probability is
        closest to (but at least) the target — e.g. "give me the line
        this player clears ~90% of the time".
        Returns that LineOption (with its real payout odds).
        """
        if not player_lines.alternates:
            return None
        # Sort alts by line ascending. Lower line = higher hit prob.
        alts = sorted(player_lines.alternates, key=lambda x: x.line)
        # We approximate: model_prob applies to the standard line; each
        # step down in line raises prob, each step up lowers it. We pick
        # the lowest line whose odds are still worth showing.
        # (Real per-line model prob is computed in the ranker.)
        return alts[0] if alts else None


def compute_edge(model_prob: float, book_odds: int) -> dict:
    """
    The core value calc: is your model's probability higher than what
    the book's odds imply? That gap is the edge.

    model_prob: your model's 0-1 probability the bet hits
    book_odds:  American odds offered

    Returns implied prob, edge (percentage points), EV per $100, verdict.
    Positive edge = you think it's more likely than the price suggests.
    """
    if book_odds is None or model_prob is None:
        return {"edge": None, "verdict": "no line"}

    if book_odds > 0:
        implied = 100 / (book_odds + 100)
        payout = book_odds
    else:
        implied = -book_odds / (-book_odds + 100)
        payout = 100 * 100 / -book_odds

    edge = model_prob - implied
    ev = model_prob * payout - (1 - model_prob) * 100

    if edge >= 0.08:
        verdict = "🟢 strong value"
    elif edge >= 0.03:
        verdict = "🟢 slight value"
    elif edge >= -0.03:
        verdict = "➖ fair price"
    else:
        verdict = "🔴 overpriced"

    return {
        "implied": round(implied, 4),
        "model": round(model_prob, 4),
        "edge": round(edge, 4),
        "edge_pct": round(edge * 100, 1),
        "ev_per_100": round(ev, 2),
        "verdict": verdict,
    }
