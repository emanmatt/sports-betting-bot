"""
analysis/projections.py

Outlier-style projection model.
Builds a projected stat line for each player using:
  - Weighted recent form (last 5 games count more than 6-10)
  - Opponent adjustment (how the opponent defends this stat)
  - Home/away split
  - Season baseline as the anchor

Then compares the projection to each book's line to find the edge.
No API credits needed — runs entirely on stored data.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from loguru import logger
from database.models import get_session, Player, PlayerStats, Game, Team

# Map normalized prop type -> PlayerStats column
STAT_COLUMN = {
    "points":      "points",
    "rebounds":    "rebounds",
    "assists":     "assists",
    "pass_yds":    "passing_yards",
    "rush_yds":    "rushing_yards",
    "rec_yds":     "receiving_yards",
    "receptions":  "receiving_yards",   # approximation
    "hits":        "hits",
    "home_runs":   "home_runs",
    "total_bases": "hits",              # approximation
    "strikeouts":  "strikeouts",
    "goals":       "goals",
    "shots":       "shots_on_goal",
}


@dataclass
class Projection:
    player_name:   str
    stat_type:     str
    # Component pieces
    season_avg:    float = None
    recent_avg:    float = None       # L5 weighted
    opponent_adj:  float = 0.0        # +/- adjustment for opponent
    home_away_adj: float = 0.0
    # Final projection
    projection:    float = None
    confidence:    str = "low"        # low / medium / high (based on sample size)
    games_used:    int = 0
    # vs line
    line:          float = None
    edge:          float = None       # projection - line
    edge_pct:      float = None
    lean:          str = ""           # over / under / pass
    game_log:      list = field(default_factory=list)


class ProjectionModel:
    """Computes opponent-adjusted projections from stored stats."""

    def __init__(self):
        self.db = get_session()

    def close(self):
        self.db.close()

    def _get_player(self, player_name: str, sport: str):
        last_name = player_name.split()[-1] if player_name else ""
        return (self.db.query(Player)
                .filter(Player.sport == sport,
                        Player.full_name.ilike(f"%{last_name}%"))
                .first())

    def _get_game_values(self, player_id: str, stat_col: str,
                         limit: int = 20) -> list[float]:
        stats = (self.db.query(PlayerStats)
                .filter_by(player_id=player_id)
                .order_by(PlayerStats.game_id.desc())
                .limit(limit)
                .all())
        vals = []
        for s in stats:
            v = getattr(s, stat_col, None)
            if v is not None:
                vals.append(float(v))
        return vals

    def _opponent_adjustment(self, opponent_team: str, sport: str,
                             stat_type: str, baseline: float) -> float:
        """
        Estimate how much the opponent inflates/suppresses this stat.
        Compares stat allowed by opponent vs league average.
        Simplified: returns a small +/- adjustment.

        Without full defensive data, we return 0 (neutral) but the
        structure is here for when defensive stats are populated.
        """
        # Placeholder for opponent defensive rating adjustment.
        # When defense-vs-position data is available, compute:
        #   adj = (opp_allowed_avg - league_avg) capped at +/- 15%
        return 0.0

    def project(self, player_name: str, sport: str, stat_type: str,
                opponent_team: str = "", is_home: bool = True,
                line: float = None) -> Projection:
        """Build a full projection for one player+stat."""
        proj = Projection(player_name=player_name, stat_type=stat_type, line=line)

        stat_col = STAT_COLUMN.get(stat_type)
        if not stat_col:
            return proj

        player = self._get_player(player_name, sport)
        if not player:
            return proj

        values = self._get_game_values(player.player_id, stat_col)
        if not values:
            return proj

        proj.games_used = len(values)
        proj.game_log = values[:10]

        # Season baseline
        proj.season_avg = round(sum(values) / len(values), 2)

        # Weighted recent (L5 = 60%, L6-10 = 40%)
        l5 = values[:5]
        l6_10 = values[5:10] if len(values) > 5 else l5
        recent = sum(l5) / len(l5)
        older = sum(l6_10) / len(l6_10) if l6_10 else recent
        proj.recent_avg = round(recent * 0.6 + older * 0.4, 2)

        # Opponent adjustment
        proj.opponent_adj = self._opponent_adjustment(
            opponent_team, sport, stat_type, proj.season_avg
        )

        # Blend: 55% recent form, 45% season baseline, + opponent adj
        base_projection = proj.recent_avg * 0.55 + proj.season_avg * 0.45
        proj.projection = round(base_projection + proj.opponent_adj, 1)

        # Confidence based on sample size
        if proj.games_used >= 10:
            proj.confidence = "high"
        elif proj.games_used >= 5:
            proj.confidence = "medium"
        else:
            proj.confidence = "low"

        # Edge vs line
        if line is not None and proj.projection is not None:
            proj.edge = round(proj.projection - line, 1)
            if line > 0:
                proj.edge_pct = round(abs(proj.edge) / line * 100, 1)
            # Lean: only call it if edge is meaningful AND confidence isn't low
            if abs(proj.edge) >= 0.5 and proj.confidence != "low":
                proj.lean = "over" if proj.edge > 0 else "under"
            else:
                proj.lean = "pass"

        return proj

    def project_prop(self, player_name: str, sport: str, stat_type: str,
                     line: float, opponent: str = "") -> dict:
        """Return projection as a dashboard-ready dict."""
        p = self.project(player_name, sport, stat_type,
                        opponent_team=opponent, line=line)
        return {
            "projection":  p.projection,
            "season_avg":  p.season_avg,
            "recent_avg":  p.recent_avg,
            "edge":        p.edge,
            "edge_pct":    p.edge_pct,
            "lean":        p.lean,
            "confidence":  p.confidence,
            "games_used":  p.games_used,
            "has_data":    p.projection is not None,
        }


# ══════════════════════════════════════════════════════════════════════
#  ARBITRAGE & +EV DETECTOR
# ══════════════════════════════════════════════════════════════════════

def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal."""
    if odds > 0:
        return 1 + odds / 100
    return 1 + 100 / abs(odds)


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability (with vig)."""
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


@dataclass
class ArbOpportunity:
    player_name:  str
    prop_label:   str
    arb_type:     str          # "arbitrage" / "middle" / "positive_ev"
    over_book:    str
    over_line:    float
    over_odds:    int
    under_book:   str
    under_line:   float
    under_odds:   int
    profit_pct:   float = 0.0   # guaranteed profit % for true arb
    middle_gap:   float = 0.0   # gap for a middle bet
    description:  str = ""


class ArbitrageDetector:
    """
    Finds arbitrage, middles, and +EV opportunities across books
    from prop data already fetched (no credits needed).
    """

    def find_arbitrage(self, multibook_props: list) -> list[ArbOpportunity]:
        """
        Scan multi-book props for arbitrage and middle opportunities.
        multibook_props: list of MultiBookProp objects.
        """
        opportunities = []

        for prop in multibook_props:
            if not prop.book_lines or len(prop.book_lines) < 2:
                continue

            # Best over (highest line + best odds) and best under (lowest line + best odds)
            over_candidates = [bl for bl in prop.book_lines
                              if bl.over_odds is not None and bl.line is not None]
            under_candidates = [bl for bl in prop.book_lines
                               if bl.under_odds is not None and bl.line is not None]

            if not over_candidates or not under_candidates:
                continue

            best_over = max(over_candidates, key=lambda x: x.over_odds)
            best_under = max(under_candidates, key=lambda x: x.under_odds)

            # ── True arbitrage: same line, combined implied prob < 100% ──
            if best_over.line == best_under.line:
                over_prob = american_to_implied_prob(best_over.over_odds)
                under_prob = american_to_implied_prob(best_under.under_odds)
                total_prob = over_prob + under_prob

                if total_prob < 1.0:
                    profit = round((1 / total_prob - 1) * 100, 2)
                    opportunities.append(ArbOpportunity(
                        player_name=prop.player_name,
                        prop_label=prop.prop_label,
                        arb_type="arbitrage",
                        over_book=best_over.sportsbook,
                        over_line=best_over.line,
                        over_odds=best_over.over_odds,
                        under_book=best_under.sportsbook,
                        under_line=best_under.line,
                        under_odds=best_under.under_odds,
                        profit_pct=profit,
                        description=(f"GUARANTEED {profit}% profit — "
                                   f"Over {best_over.line} ({best_over.over_odds:+d}) "
                                   f"@ {best_over.sportsbook.upper()} + "
                                   f"Under {best_under.line} ({best_under.under_odds:+d}) "
                                   f"@ {best_under.sportsbook.upper()}")
                    ))

            # ── Middle: under line is HIGHER than over line ──
            # e.g. Over 24.5 at book A, Under 26.5 at book B
            # If result lands on 25 or 26, BOTH bets win
            elif best_under.line > best_over.line:
                gap = round(best_under.line - best_over.line, 1)
                opportunities.append(ArbOpportunity(
                    player_name=prop.player_name,
                    prop_label=prop.prop_label,
                    arb_type="middle",
                    over_book=best_over.sportsbook,
                    over_line=best_over.line,
                    over_odds=best_over.over_odds,
                    under_book=best_under.sportsbook,
                    under_line=best_under.line,
                    under_odds=best_under.under_odds,
                    middle_gap=gap,
                    description=(f"MIDDLE opportunity ({gap} pt gap) — "
                               f"Over {best_over.line} @ {best_over.sportsbook.upper()} + "
                               f"Under {best_under.line} @ {best_under.sportsbook.upper()}. "
                               f"Both win if result lands in the gap.")
                ))

        # Sort: arbs first (by profit), then middles (by gap)
        opportunities.sort(
            key=lambda x: (x.arb_type != "arbitrage", -x.profit_pct, -x.middle_gap)
        )
        logger.info(f"[Arb] Found {len(opportunities)} opportunities "
                   f"({sum(1 for o in opportunities if o.arb_type=='arbitrage')} arbs, "
                   f"{sum(1 for o in opportunities if o.arb_type=='middle')} middles)")
        return opportunities

    def find_positive_ev(self, multibook_props: list,
                         projection_model: ProjectionModel,
                         sport: str) -> list[dict]:
        """
        Find +EV bets by comparing our projection to the book's implied line.
        If our projection strongly favors a side the market underprices, that's +EV.
        """
        ev_bets = []

        for prop in multibook_props:
            if not prop.consensus_line or not prop.book_lines:
                continue

            # Get our projection
            proj = projection_model.project(
                prop.player_name, sport, prop.prop_type,
                opponent_team=prop.away_team, line=prop.consensus_line
            )

            if proj.projection is None or proj.confidence == "low":
                continue

            if abs(proj.edge or 0) < 1.0:
                continue  # Not enough edge

            # Find the best odds for our leaned side
            if proj.lean == "over":
                candidates = [bl for bl in prop.book_lines if bl.over_odds]
                if candidates:
                    best = max(candidates, key=lambda x: x.over_odds)
                    ev_bets.append({
                        "player": prop.player_name,
                        "prop": prop.prop_label,
                        "side": "OVER",
                        "line": best.line,
                        "odds": best.over_odds,
                        "book": best.sportsbook,
                        "projection": proj.projection,
                        "edge": proj.edge,
                        "confidence": proj.confidence,
                    })
            elif proj.lean == "under":
                candidates = [bl for bl in prop.book_lines if bl.under_odds]
                if candidates:
                    best = max(candidates, key=lambda x: x.under_odds)
                    ev_bets.append({
                        "player": prop.player_name,
                        "prop": prop.prop_label,
                        "side": "UNDER",
                        "line": best.line,
                        "odds": best.under_odds,
                        "book": best.sportsbook,
                        "projection": proj.projection,
                        "edge": proj.edge,
                        "confidence": proj.confidence,
                    })

        ev_bets.sort(key=lambda x: abs(x["edge"]), reverse=True)
        logger.info(f"[EV] Found {len(ev_bets)} +EV bets.")
        return ev_bets
