"""
analysis/hit_rate.py

Calculates player hit rates and trends for props:
  - How often did the player hit this line in last 10/5 games?
  - Recent form trend (hot/cold)
  - Simple projection (weighted recent average)

This is the Outlier-style "L10" data that makes props analyzable.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from loguru import logger
from database.models import get_session, Player, PlayerStats, Game

# Map normalized prop type to the PlayerStats column
STAT_COLUMN = {
    "points":      "points",
    "rebounds":    "rebounds",
    "assists":     "assists",
    "threes":      "three_pt_pct",   # note: this is pct, need makes
    "pass_yds":    "passing_yards",
    "rush_yds":    "rushing_yards",
    "rec_yds":     "receiving_yards",
    "hits":        "hits",
    "home_runs":   "home_runs",
    "strikeouts":  "strikeouts",
    "goals":       "goals",
    "shots":       "shots_on_goal",
}


@dataclass
class HitRateResult:
    player_name:   str
    stat_type:     str
    line:          float
    # Hit rates
    l5_hits:       int = 0
    l5_total:      int = 0
    l5_rate:       float = 0.0
    l10_hits:      int = 0
    l10_total:     int = 0
    l10_rate:      float = 0.0
    season_hits:   int = 0
    season_total:  int = 0
    season_rate:   float = 0.0
    # Averages
    l5_avg:        float = None
    l10_avg:       float = None
    season_avg:    float = None
    # Projection
    projection:    float = None
    trend:         str = ""       # hot / cold / stable
    game_log:      list = field(default_factory=list)  # recent values


class HitRateCalculator:
    """Computes hit rates and projections from stored player stats."""

    def __init__(self):
        self.db = get_session()

    def close(self):
        self.db.close()

    def _get_stat_values(self, player_name: str, sport: str,
                         stat_type: str, limit: int = 20) -> list[float]:
        """Get recent game-by-game values for a stat."""
        column = STAT_COLUMN.get(stat_type)
        if not column:
            return []

        # Find player
        last_name = player_name.split()[-1] if player_name else ""
        player = (self.db.query(Player)
                 .filter(Player.sport == sport,
                         Player.full_name.ilike(f"%{last_name}%"))
                 .first())
        if not player:
            return []

        # Get recent stats
        stats = (self.db.query(PlayerStats)
                .filter_by(player_id=player.player_id)
                .order_by(PlayerStats.game_id.desc())
                .limit(limit)
                .all())

        values = []
        for s in stats:
            val = getattr(s, column, None)
            if val is not None:
                values.append(float(val))
        return values

    def calculate(self, player_name: str, sport: str,
                  stat_type: str, line: float) -> HitRateResult:
        """
        Calculate full hit rate analysis for a player prop.
        """
        result = HitRateResult(
            player_name=player_name,
            stat_type=stat_type,
            line=line,
        )

        values = self._get_stat_values(player_name, sport, stat_type)
        if not values:
            return result

        result.game_log = values[:10]

        # L5
        l5 = values[:5]
        if l5:
            result.l5_hits = sum(1 for v in l5 if v > line)
            result.l5_total = len(l5)
            result.l5_rate = round(result.l5_hits / result.l5_total * 100)
            result.l5_avg = round(sum(l5) / len(l5), 1)

        # L10
        l10 = values[:10]
        if l10:
            result.l10_hits = sum(1 for v in l10 if v > line)
            result.l10_total = len(l10)
            result.l10_rate = round(result.l10_hits / result.l10_total * 100)
            result.l10_avg = round(sum(l10) / len(l10), 1)

        # Season (all available)
        if values:
            result.season_hits = sum(1 for v in values if v > line)
            result.season_total = len(values)
            result.season_rate = round(result.season_hits / result.season_total * 100)
            result.season_avg = round(sum(values) / len(values), 1)

        # Projection: weighted (recent games count more)
        if len(values) >= 3:
            # Weight last 5 at 60%, games 6-10 at 40%
            recent = values[:5]
            older = values[5:10] if len(values) > 5 else recent
            recent_avg = sum(recent) / len(recent)
            older_avg = sum(older) / len(older) if older else recent_avg
            result.projection = round(recent_avg * 0.6 + older_avg * 0.4, 1)

        # Trend
        if result.l5_avg and result.season_avg:
            if result.l5_avg > result.season_avg * 1.1:
                result.trend = "hot"
            elif result.l5_avg < result.season_avg * 0.9:
                result.trend = "cold"
            else:
                result.trend = "stable"

        return result

    def enrich_prop(self, player_name: str, sport: str,
                    stat_type: str, line: float) -> dict:
        """Return hit rate data as a dict for dashboard display."""
        r = self.calculate(player_name, sport, stat_type, line)
        return {
            "l5_rate":     r.l5_rate,
            "l5_display":  f"{r.l5_hits}/{r.l5_total}" if r.l5_total else "N/A",
            "l10_rate":    r.l10_rate,
            "l10_display": f"{r.l10_hits}/{r.l10_total}" if r.l10_total else "N/A",
            "season_rate": r.season_rate,
            "l10_avg":     r.l10_avg,
            "projection":  r.projection,
            "trend":       r.trend,
            "game_log":    r.game_log,
            "has_data":    r.l10_total > 0,
        }
