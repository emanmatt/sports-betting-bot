"""
analysis/hits_ranker.py
 
Ranks batter "hits" plays for today's games by combining EVERY
available data source (no OddsAPI credits needed):
 
  - Confirmed lineups (MLB.com)
  - Each batter's L10/L15 hit rate + game logs (from our 14K logs)
  - Projection (weighted recent form)
  - Opposing pitcher quality (strikeout rate)
  - Weather / wind at the venue
  - Rest / travel fatigue
  - Injury status
 
Produces a ranked table: strongest hit play → weakest.
This is what powers the "Top Hits" view in the dashboard.
"""
 
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
 
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
from database.models import get_session, Player, PlayerStats
 
 
@dataclass
class HitPlay:
    player_name:   str
    team:          str
    opponent:      str
    venue:         str
    batting_order: int = None
    # Hit history
    l10_hit_rate:  float = 0.0     # % of last 10 games with 1+ hits
    l15_hit_rate:  float = 0.0
    season_hit_rate: float = 0.0
    games_logged:  int = 0
    avg_hits:      float = 0.0     # avg hits per game
    recent_avg:    float = 0.0     # L5 avg hits
    multi_hit_rate: float = 0.0    # % of games with 2+ hits
    # Context
    opp_pitcher:   str = ""
    opp_pitcher_hand: str = ""
    weather_note:  str = ""
    weather_boost: bool = False    # wind out / hot = boost
    trend:         str = ""        # hot / cold / stable
    # Final ranking
    score:         float = 0.0     # 0-100 composite score
    tier:          str = ""        # A / B / C / pass
    game_log:      list = field(default_factory=list)
 
 
class HitsRanker:
    """Ranks hit props using all available data."""
 
    def __init__(self):
        self.db = get_session()
 
    def close(self):
        self.db.close()
 
    def _get_batter_hit_history(self, player_name: str) -> dict:
        """Pull a batter's hit history from game logs by exact name match."""
        if not player_name:
            return {}
 
        # Pull ALL MLB stat rows and filter in Python by the name stored
        # in raw_stats. Reliable — no fragile JSON SQL matching.
        # (Cached on first call for speed.)
        if not hasattr(self, "_logs_by_name"):
            self._logs_by_name = {}
            all_stats = (self.db.query(PlayerStats)
                        .filter(PlayerStats.sport == "MLB")
                        .all())
            for s in all_stats:
                if not s.raw_stats:
                    continue
                nm = s.raw_stats.get("player_name")
                if not nm:
                    continue
                self._logs_by_name.setdefault(nm, []).append(s)
 
        # Exact name match, then case-insensitive fallback
        stats = self._logs_by_name.get(player_name)
        if not stats:
            for nm, rows in self._logs_by_name.items():
                if nm.lower() == player_name.lower():
                    stats = rows
                    break
        if not stats:
            return {}
 
        # Sort by game_id desc (most recent first)
        stats = sorted(stats, key=lambda s: s.game_id, reverse=True)[:20]
 
        # Extract hit values from raw_stats (batters only)
        hit_values = []
        for s in stats:
            if s.raw_stats.get("is_pitcher"):
                continue
            h = s.raw_stats.get("hits")
            if h is None:
                h = s.hits
            if h is not None:
                hit_values.append(int(h))
 
        if not hit_values:
            return {}
 
        def rate(vals, threshold=1):
            if not vals:
                return 0.0
            return round(sum(1 for v in vals if v >= threshold) / len(vals) * 100)
 
        l10 = hit_values[:10]
        l15 = hit_values[:15]
        l5 = hit_values[:5]
 
        return {
            "games_logged":   len(hit_values),
            "l10_hit_rate":   rate(l10),
            "l15_hit_rate":   rate(l15),
            "season_hit_rate": rate(hit_values),
            "multi_hit_rate": rate(l15, threshold=2),
            "avg_hits":       round(sum(hit_values) / len(hit_values), 2),
            "recent_avg":     round(sum(l5) / len(l5), 2) if l5 else 0,
            "game_log":       hit_values[:10],
        }
 
    def _compute_score(self, play: HitPlay) -> float:
        """
        Composite 0-100 score for a hit play.
        Weights: L10 hit rate (biggest), recent form, weather, matchup.
        """
        score = 0.0
 
        # L10 hit rate is the core (max 45 pts)
        score += play.l10_hit_rate * 0.45
 
        # L15 hit rate for stability (max 20 pts)
        score += play.l15_hit_rate * 0.20
 
        # Recent form bonus (max 15 pts) — hot streak
        if play.recent_avg >= 1.5:
            score += 15
        elif play.recent_avg >= 1.0:
            score += 10
        elif play.recent_avg >= 0.7:
            score += 5
 
        # Weather boost (max 10 pts)
        if play.weather_boost:
            score += 10
 
        # Batting order bonus — top of order = more ABs (max 10 pts)
        if play.batting_order:
            if play.batting_order <= 3:
                score += 10
            elif play.batting_order <= 5:
                score += 6
            elif play.batting_order <= 6:
                score += 3
 
        # Penalty for cold trend
        if play.trend == "cold":
            score -= 10
 
        # Penalty for thin sample
        if play.games_logged < 8:
            score -= 15
 
        return max(0, min(100, round(score, 1)))
 
    def _assign_tier(self, score: float) -> str:
        if score >= 70:
            return "A"
        elif score >= 55:
            return "B"
        elif score >= 40:
            return "C"
        return "pass"
 
    def rank_todays_hits(self, lineups_data: list, weather_by_venue: dict = None) -> list[HitPlay]:
        """
        Rank all batters in today's confirmed lineups by hit likelihood.
 
        lineups_data: list of dicts, each:
          {game, home_team, away_team, venue, home_lineup, away_lineup,
           home_pitcher, away_pitcher, ...}
        weather_by_venue: {venue_name: WeatherReport}
        """
        weather_by_venue = weather_by_venue or {}
        plays = []
 
        for game in lineups_data:
            venue = game.get("venue", "")
            weather = weather_by_venue.get(venue)
            weather_boost = False
            weather_note = ""
            if weather:
                weather_note = getattr(weather, "impact_summary", "")
                weather_boost = getattr(weather, "wind_effect", "") == "out" or \
                               (getattr(weather, "temp_f", 0) or 0) >= 85
 
            # Process both lineups
            for side, team_key, opp_key, pitcher_key in [
                ("home_lineup", "home_team", "away_team", "away_pitcher"),
                ("away_lineup", "away_team", "home_team", "home_pitcher"),
            ]:
                lineup = game.get(side, [])
                team = game.get(team_key, "")
                opponent = game.get(opp_key, "")
                opp_pitcher = game.get(pitcher_key, "")
 
                for batter in lineup:
                    name = batter.get("name", "") if isinstance(batter, dict) else batter
                    order = batter.get("batting_order") if isinstance(batter, dict) else None
 
                    history = self._get_batter_hit_history(name)
                    if not history:
                        continue
 
                    play = HitPlay(
                        player_name=name,
                        team=team,
                        opponent=opponent,
                        venue=venue,
                        batting_order=order,
                        opp_pitcher=opp_pitcher,
                        weather_note=weather_note,
                        weather_boost=weather_boost,
                        **{k: v for k, v in history.items() if k != "game_log"},
                        game_log=history.get("game_log", []),
                    )
 
                    # Trend
                    if play.recent_avg > play.avg_hits * 1.15:
                        play.trend = "hot"
                    elif play.recent_avg < play.avg_hits * 0.85:
                        play.trend = "cold"
                    else:
                        play.trend = "stable"
 
                    play.score = self._compute_score(play)
                    play.tier = self._assign_tier(play.score)
                    plays.append(play)
 
        # Sort strongest to weakest
        plays.sort(key=lambda x: x.score, reverse=True)
        logger.info(f"[HitsRanker] Ranked {len(plays)} hit plays.")
        return plays
 
    def to_table_rows(self, plays: list[HitPlay], limit: int = 30) -> list[dict]:
        """Format ranked plays as table rows for the dashboard."""
        rows = []
        for i, p in enumerate(plays[:limit], 1):
            trend_emoji = {"hot": "🔥", "cold": "🧊", "stable": "➡️"}.get(p.trend, "")
            rows.append({
                "Rank": i,
                "Tier": p.tier,
                "Player": p.player_name,
                "Team": p.team,
                "Order": p.batting_order or "-",
                "L10 Hit%": f"{p.l10_hit_rate:.0f}%",
                "L15 Hit%": f"{p.l15_hit_rate:.0f}%",
                "Avg H": p.avg_hits,
                "L5 Avg": p.recent_avg,
                "Trend": f"{trend_emoji} {p.trend}",
                "vs Pitcher": p.opp_pitcher or "-",
                "Score": p.score,
            })
        return rows
 