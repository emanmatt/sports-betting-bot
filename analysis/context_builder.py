"""
analysis/context_builder.py

Before the AI can analyze a game, it needs all the relevant data
assembled in one place. This module pulls everything from the DB:
  - Head-to-head history
  - Current rosters + injury status
  - Recent form (last 10 games)
  - Live odds + line movement
  - News from last 48hrs
  - Reddit/social posts from last 6hrs
  - Contract incentive clauses for key players
  - Venue / environment context

Output is a structured GameContext object the AI prompt builder uses.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger
from database.models import (
    get_session, Team, Player, Game, GameOdds,
    InjuryReport, NewsArticle, SocialPost,
    PlayerContract, PlayerStats, TeamMatchupHistory
)


@dataclass
class PlayerContext:
    """Everything about a single player relevant to betting."""
    player_id:      str
    name:           str
    position:       str
    status:         str                        # Active / Injured / Questionable
    injury_detail:  str = ""
    recent_stats:   dict = field(default_factory=dict)   # Last 5 game averages
    season_avg:     dict = field(default_factory=dict)
    vs_opponent:    dict = field(default_factory=dict)   # Stats vs this specific team
    contract_incentives: list = field(default_factory=list)
    has_active_incentive: bool = False         # Close to hitting a bonus?
    social_mentions: list = field(default_factory=list)  # Recent tweets/posts about them


@dataclass
class TeamContext:
    """Everything about a team for a specific game."""
    team_id:        str
    name:           str
    abbreviation:   str
    is_home:        bool
    # Record
    wins:           int = 0
    losses:         int = 0
    # Recent form
    last_10_record: str = ""                   # e.g. "7-3"
    last_10_ats:    str = ""                   # Against the spread: "6-4"
    home_record:    str = ""
    away_record:    str = ""
    # Rankings
    offense_rank:   int = 0
    defense_rank:   int = 0
    pace_rank:      int = 0
    # Head-to-head
    h2h_all_time:   str = ""                   # "Lakers lead series 124-115"
    h2h_last_5:     list = field(default_factory=list)
    h2h_ats_record: str = ""
    # Key players
    players:        list[PlayerContext] = field(default_factory=list)
    # Injury report
    injured_out:    list[str] = field(default_factory=list)
    injured_questionable: list[str] = field(default_factory=list)
    # Rest
    days_rest:      int = 0
    is_back_to_back: bool = False


@dataclass
class OddsContext:
    """Current lines and movement history."""
    # Current best lines across books
    home_moneyline:   Optional[int] = None
    away_moneyline:   Optional[int] = None
    spread:           Optional[float] = None     # Negative = home favored
    total:            Optional[float] = None
    # Line movement
    opening_spread:   Optional[float] = None
    opening_total:    Optional[float] = None
    spread_moved:     float = 0.0               # How much spread moved from open
    total_moved:      float = 0.0
    movement_direction: str = ""                # "toward home" / "toward away"
    # Sharp money signals
    sharp_action:     Optional[str] = None      # "home" / "away" / "over" / "under"
    significant_move: bool = False              # Move of 1.5+ points
    # Book-by-book
    book_lines:       list = field(default_factory=list)


@dataclass
class GameContext:
    """Complete betting context for one game — fed directly to the AI."""
    sport:          str
    game_id:        str
    game_date:      datetime
    home_team:      TeamContext
    away_team:      TeamContext
    odds:           OddsContext
    venue_name:     str = ""
    venue_city:     str = ""
    altitude_ft:    int = 0
    temperature:    Optional[float] = None
    weather_desc:   str = ""
    referee_names:  list = field(default_factory=list)
    # Soft data
    recent_news:    list[str] = field(default_factory=list)   # Headlines
    social_buzz:    list[str] = field(default_factory=list)   # Reddit/Twitter posts
    high_impact_alerts: list[str] = field(default_factory=list)
    # Metadata
    built_at:       datetime = field(default_factory=datetime.utcnow)


class ContextBuilder:
    """Assembles all database data into a GameContext for AI analysis."""

    def __init__(self):
        self.db = get_session()

    def close(self):
        self.db.close()

    # ── Internal helpers ──────────────────────────────────────────────

    def _get_team(self, team_id: str) -> Optional[Team]:
        return self.db.query(Team).filter_by(team_id=team_id).first()

    def _get_recent_games(self, team_id: str, sport: str,
                          n: int = 10) -> list[Game]:
        """Get the last N completed games for a team."""
        return (self.db.query(Game)
                .filter(
                    Game.sport == sport,
                    Game.status == "Final",
                    ((Game.home_team_id == team_id) |
                     (Game.away_team_id == team_id))
                )
                .order_by(Game.game_date.desc())
                .limit(n)
                .all())

    def _calc_recent_record(self, team_id: str, games: list[Game]) -> str:
        """Calculate W-L from recent games."""
        wins = losses = 0
        for g in games:
            if g.winner_id == team_id:
                wins += 1
            elif g.status == "Final" and g.winner_id and g.winner_id != team_id:
                losses += 1
        return f"{wins}-{losses}"

    def _get_days_rest(self, team_id: str, game_date: datetime,
                        sport: str) -> int:
        """Calculate days of rest since last game."""
        last_game = (self.db.query(Game)
                     .filter(
                         Game.sport == sport,
                         Game.status == "Final",
                         Game.game_date < game_date,
                         ((Game.home_team_id == team_id) |
                          (Game.away_team_id == team_id))
                     )
                     .order_by(Game.game_date.desc())
                     .first())
        if not last_game:
            return 7  # Assume well-rested if no data
        delta = game_date - last_game.game_date
        return max(0, delta.days)

    def _get_player_recent_stats(self, player_id: str,
                                  n: int = 5) -> dict:
        """Average stats over last N games."""
        stats = (self.db.query(PlayerStats)
                 .filter_by(player_id=player_id)
                 .order_by(PlayerStats.game_id.desc())
                 .limit(n)
                 .all())
        if not stats:
            return {}
        count = len(stats)
        return {
            "games":    count,
            "points":   round(sum(s.points or 0 for s in stats) / count, 1),
            "assists":  round(sum(s.assists or 0 for s in stats) / count, 1),
            "rebounds": round(sum(s.rebounds or 0 for s in stats) / count, 1),
            "minutes":  round(sum(s.minutes or 0 for s in stats) / count, 1),
        }

    def _get_player_vs_team(self, player_id: str,
                             opponent_team_id: str) -> dict:
        """Historical stats for a player vs a specific opponent."""
        # Join through games to find matchups
        stats = (self.db.query(PlayerStats)
                 .join(Game, PlayerStats.game_id == Game.game_id)
                 .filter(
                     PlayerStats.player_id == player_id,
                     ((Game.home_team_id == opponent_team_id) |
                      (Game.away_team_id == opponent_team_id))
                 )
                 .limit(10)
                 .all())
        if not stats:
            return {}
        count = len(stats)
        return {
            "games_vs_opponent": count,
            "avg_points": round(sum(s.points or 0 for s in stats) / count, 1),
            "avg_assists": round(sum(s.assists or 0 for s in stats) / count, 1),
            "avg_rebounds": round(sum(s.rebounds or 0 for s in stats) / count, 1),
        }

    def _get_contract_incentives(self, player_id: str) -> tuple[list, bool]:
        """
        Get active incentive clauses and flag if player is close to hitting one.
        Returns (incentives_list, has_active_incentive_flag)
        """
        contract = (self.db.query(PlayerContract)
                    .filter_by(player_id=player_id)
                    .first())
        if not contract or not contract.incentives:
            return [], False

        active = []
        for inc in contract.incentives:
            # Flag as "active" if labeled likely or has a close threshold
            is_active = (inc.get("likely", False) or
                         inc.get("bonus_amount", 0) > 500_000)
            if is_active:
                active.append(inc)

        return contract.incentives, len(active) > 0

    def _build_team_context(self, team_id: str, game: Game,
                             is_home: bool) -> TeamContext:
        """Build full TeamContext for one side of a game."""
        team = self._get_team(team_id)
        if not team:
            return TeamContext(team_id=team_id, name="Unknown",
                               abbreviation="?", is_home=is_home)

        recent_games = self._get_recent_games(team_id, game.sport, n=10)
        days_rest = self._get_days_rest(team_id, game.game_date, game.sport)

        opponent_id = (game.away_team_id if is_home else game.home_team_id)

        # Build player contexts for active roster
        players = self.db.query(Player).filter_by(
            team_id=team_id, sport=game.sport
        ).all()

        player_contexts = []
        injured_out = []
        injured_questionable = []

        for p in players[:15]:  # Cap at 15 players per team
            # Recent injury status
            injury = (self.db.query(InjuryReport)
                      .filter_by(player_id=p.player_id)
                      .order_by(InjuryReport.captured_at.desc())
                      .first())

            status = p.status or "Active"
            injury_detail = ""
            if injury:
                status = injury.status
                injury_detail = injury.injury_type or ""
                if injury.status in ["Out", "IR"]:
                    injured_out.append(p.full_name)
                elif injury.status in ["Doubtful", "Questionable", "GTD"]:
                    injured_questionable.append(p.full_name)

            # Stats
            recent_stats = self._get_player_recent_stats(p.player_id)
            vs_opponent  = self._get_player_vs_team(p.player_id, opponent_id)
            incentives, has_active = self._get_contract_incentives(p.player_id)

            # Social mentions in last 6 hours
            cutoff = datetime.utcnow() - timedelta(hours=6)
            mentions = (self.db.query(SocialPost)
                        .filter(
                            SocialPost.sport == game.sport,
                            SocialPost.published_at >= cutoff,
                            SocialPost.betting_impact == "high",
                        )
                        .all())
            player_mentions = [
                m.content[:200] for m in mentions
                if p.full_name in (m.content or "")
            ]

            player_contexts.append(PlayerContext(
                player_id=p.player_id,
                name=p.full_name,
                position=p.position or "",
                status=status,
                injury_detail=injury_detail,
                recent_stats=recent_stats,
                vs_opponent=vs_opponent,
                contract_incentives=incentives,
                has_active_incentive=has_active,
                social_mentions=player_mentions,
            ))

        return TeamContext(
            team_id=team_id,
            name=team.name,
            abbreviation=team.abbreviation,
            is_home=is_home,
            wins=team.wins or 0,
            losses=team.losses or 0,
            offense_rank=team.offense_rank or 0,
            defense_rank=team.defense_rank or 0,
            last_10_record=self._calc_recent_record(team_id, recent_games),
            players=player_contexts,
            injured_out=injured_out,
            injured_questionable=injured_questionable,
            days_rest=days_rest,
            is_back_to_back=(days_rest == 1),
        )

    def _build_odds_context(self, game_id: str) -> OddsContext:
        """Build odds context with line movement analysis."""
        # Get latest odds across all books
        latest = (self.db.query(GameOdds)
                  .filter_by(game_id=game_id)
                  .order_by(GameOdds.captured_at.desc())
                  .limit(20)
                  .all())

        if not latest:
            return OddsContext()

        # Best current line (use DraftKings or first available)
        best = next((o for o in latest if o.sportsbook == "draftkings"),
                    latest[0])

        # Opening line (earliest capture)
        all_odds = (self.db.query(GameOdds)
                    .filter_by(game_id=game_id)
                    .order_by(GameOdds.captured_at.asc())
                    .first())

        spread_moved = 0.0
        total_moved  = 0.0
        if all_odds and best.spread and all_odds.spread:
            spread_moved = round(best.spread - all_odds.spread, 1)
        if all_odds and best.total_over_under and all_odds.total_over_under:
            total_moved = round(best.total_over_under - all_odds.total_over_under, 1)

        significant = abs(spread_moved) >= 1.5 or abs(total_moved) >= 2.0

        # Movement direction (negative spread = home favored)
        direction = ""
        if spread_moved > 0:
            direction = "toward away (underdog getting sharp money)"
        elif spread_moved < 0:
            direction = "toward home (favorite getting more action)"

        return OddsContext(
            home_moneyline=best.home_moneyline,
            away_moneyline=best.away_moneyline,
            spread=best.spread,
            total=best.total_over_under,
            opening_spread=all_odds.spread if all_odds else best.spread,
            opening_total=all_odds.total_over_under if all_odds else best.total_over_under,
            spread_moved=spread_moved,
            total_moved=total_moved,
            movement_direction=direction,
            significant_move=significant,
            book_lines=[{
                "book": o.sportsbook,
                "spread": o.spread,
                "total": o.total_over_under,
                "home_ml": o.home_moneyline,
            } for o in latest[:7]],
        )

    def _get_recent_news(self, sport: str, team_names: list[str],
                          hours: int = 48) -> tuple[list[str], list[str]]:
        """Get relevant news headlines and any high-impact alerts."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        articles = (self.db.query(NewsArticle)
                    .filter(
                        NewsArticle.sport == sport,
                        NewsArticle.published_at >= cutoff,
                    )
                    .order_by(NewsArticle.published_at.desc())
                    .limit(50)
                    .all())

        headlines = []
        alerts = []
        for a in articles:
            # Include if mentions one of our teams or is high-impact
            relevant = (a.betting_impact in ["high", "medium"] or
                        any(name.split()[0] in (a.title or "")
                            for name in team_names))
            if relevant:
                headline = f"[{a.source}] {a.title}"
                headlines.append(headline)
                if a.betting_impact == "high":
                    alerts.append(headline)

        return headlines[:20], alerts[:5]

    def _get_social_buzz(self, sport: str, team_names: list[str],
                          hours: int = 6) -> list[str]:
        """Get recent high-signal Reddit/Twitter posts."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        posts = (self.db.query(SocialPost)
                 .filter(
                     SocialPost.sport == sport,
                     SocialPost.published_at >= cutoff,
                     SocialPost.betting_impact.in_(["high", "medium"]),
                 )
                 .order_by(SocialPost.upvotes.desc())
                 .limit(30)
                 .all())

        buzz = []
        for p in posts:
            relevant = any(name.split()[0] in (p.content or "")
                           for name in team_names)
            if relevant or p.is_verified_source:
                prefix = "⭐ [VERIFIED]" if p.is_verified_source else f"[{p.source_name}]"
                buzz.append(f"{prefix} {p.content[:300]}")

        return buzz[:15]

    # ── Main public method ─────────────────────────────────────────────

    def build(self, game_id: str) -> Optional[GameContext]:
        """
        Build a complete GameContext for a game.
        This is the single method the AI engine calls.
        """
        game = self.db.query(Game).filter_by(game_id=game_id).first()
        if not game:
            logger.error(f"[ContextBuilder] Game not found: {game_id}")
            return None

        logger.info(f"[ContextBuilder] Building context for {game_id}...")

        home_ctx = self._build_team_context(
            game.home_team_id, game, is_home=True
        )
        away_ctx = self._build_team_context(
            game.away_team_id, game, is_home=False
        )
        odds_ctx = self._build_odds_context(game_id)

        team_names = [home_ctx.name, away_ctx.name]
        news, alerts = self._get_recent_news(game.sport, team_names)
        social = self._get_social_buzz(game.sport, team_names)

        context = GameContext(
            sport=game.sport,
            game_id=game_id,
            game_date=game.game_date,
            home_team=home_ctx,
            away_team=away_ctx,
            odds=odds_ctx,
            venue_name=game.venue_name or "",
            venue_city=game.venue_city or "",
            altitude_ft=game.altitude_ft or 0,
            temperature=game.temperature,
            weather_desc=game.weather_desc or "",
            referee_names=game.referee_names or [],
            recent_news=news,
            social_buzz=social,
            high_impact_alerts=alerts,
        )

        logger.info(f"[ContextBuilder] ✅ Context built: "
                    f"{away_ctx.name} @ {home_ctx.name} | "
                    f"Spread: {odds_ctx.spread} | "
                    f"{len(news)} news items | {len(social)} social posts")
        return context

    def get_todays_games(self, sport: str) -> list[Game]:
        """Get all scheduled games for today."""
        today = datetime.utcnow().date()
        return (self.db.query(Game)
                .filter(
                    Game.sport == sport,
                    Game.status == "Scheduled",
                )
                .all())
