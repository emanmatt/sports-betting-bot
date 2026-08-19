"""
database/models.py
All database table definitions using SQLAlchemy ORM.
Run database/init_db.py to create these tables in PostgreSQL.
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, JSON, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from config.settings import DATABASE_URL

Base = declarative_base()


# ══════════════════════════════════════════════════════════════════════
#  TEAMS
# ══════════════════════════════════════════════════════════════════════

class Team(Base):
    __tablename__ = "teams"

    id            = Column(Integer, primary_key=True)
    sport         = Column(String(10), nullable=False)          # NBA / NFL / MLB / NHL
    league        = Column(String(20), nullable=False)
    team_id       = Column(String(50), unique=True, nullable=False)  # ESPN team ID
    name          = Column(String(100), nullable=False)
    abbreviation  = Column(String(10), nullable=False)
    city          = Column(String(100))
    conference    = Column(String(50))
    division      = Column(String(50))
    venue_name    = Column(String(100))
    venue_city    = Column(String(100))
    venue_state   = Column(String(50))
    venue_capacity= Column(Integer)
    # Season record
    wins          = Column(Integer, default=0)
    losses        = Column(Integer, default=0)
    win_pct       = Column(Float, default=0.0)
    # Ranking
    offense_rank  = Column(Integer)
    defense_rank  = Column(Integer)
    # Metadata
    logo_url      = Column(String(500))
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    players = relationship("Player", back_populates="team")
    home_games = relationship("Game", foreign_keys="Game.home_team_id", back_populates="home_team")
    away_games = relationship("Game", foreign_keys="Game.away_team_id", back_populates="away_team")


# ══════════════════════════════════════════════════════════════════════
#  PLAYERS
# ══════════════════════════════════════════════════════════════════════

class Player(Base):
    __tablename__ = "players"

    id              = Column(Integer, primary_key=True)
    sport           = Column(String(10), nullable=False)
    player_id       = Column(String(50), unique=True, nullable=False)  # ESPN player ID
    team_id         = Column(String(50), ForeignKey("teams.team_id"))
    full_name       = Column(String(100), nullable=False)
    first_name      = Column(String(50))
    last_name       = Column(String(50))
    position        = Column(String(20))
    jersey_number   = Column(String(5))
    # Physical
    height          = Column(String(10))
    weight          = Column(Integer)
    age             = Column(Integer)
    date_of_birth   = Column(String(20))
    # Career
    years_experience= Column(Integer)
    college         = Column(String(100))
    draft_year      = Column(Integer)
    draft_round     = Column(Integer)
    draft_pick      = Column(Integer)
    # Status
    status          = Column(String(50), default="Active")   # Active / Injured / Suspended
    injury_status   = Column(String(50))                     # Questionable / Doubtful / Out
    injury_detail   = Column(Text)
    # Social
    twitter_handle  = Column(String(100))
    instagram_handle= Column(String(100))
    # Metadata
    headshot_url    = Column(String(500))
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = relationship("Team", back_populates="players")
    stats = relationship("PlayerStats", back_populates="player")
    contract = relationship("PlayerContract", back_populates="player", uselist=False)
    injury_reports = relationship("InjuryReport", back_populates="player")


# ══════════════════════════════════════════════════════════════════════
#  GAMES
# ══════════════════════════════════════════════════════════════════════

class Game(Base):
    __tablename__ = "games"

    id              = Column(Integer, primary_key=True)
    sport           = Column(String(10), nullable=False)
    game_id         = Column(String(50), unique=True, nullable=False)  # ESPN game ID
    home_team_id    = Column(String(50), ForeignKey("teams.team_id"))
    away_team_id    = Column(String(50), ForeignKey("teams.team_id"))
    # Schedule
    game_date       = Column(DateTime, nullable=False)
    season_year     = Column(Integer)
    season_type     = Column(String(20))                    # Regular / Playoffs / Preseason
    week            = Column(Integer)                       # NFL week number
    # Result
    status          = Column(String(20), default="Scheduled")  # Scheduled / InProgress / Final
    home_score      = Column(Integer)
    away_score      = Column(Integer)
    winner_id       = Column(String(50))
    # Venue & environment
    venue_name      = Column(String(100))
    venue_city      = Column(String(100))
    attendance      = Column(Integer)
    temperature     = Column(Float)                         # For outdoor sports
    weather_desc    = Column(String(200))                   # "Partly cloudy, wind 12mph NW"
    altitude_ft     = Column(Integer)                       # Denver = 5280 ft
    # Officials / Referees
    referee_names   = Column(JSON)                          # ["Ref1", "Ref2"]
    # Metadata
    broadcast       = Column(String(50))
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    home_team = relationship("Team", foreign_keys=[home_team_id], back_populates="home_games")
    away_team = relationship("Team", foreign_keys=[away_team_id], back_populates="away_games")
    odds = relationship("GameOdds", back_populates="game")
    player_stats = relationship("PlayerStats", back_populates="game")


# ══════════════════════════════════════════════════════════════════════
#  ODDS & LINES
# ══════════════════════════════════════════════════════════════════════

class GameOdds(Base):
    __tablename__ = "game_odds"

    id              = Column(Integer, primary_key=True)
    game_id         = Column(String(50), ForeignKey("games.game_id"))
    sport           = Column(String(10))
    sportsbook      = Column(String(50))                    # DraftKings / FanDuel / etc.
    # Lines
    home_moneyline  = Column(Integer)                       # e.g. -150
    away_moneyline  = Column(Integer)                       # e.g. +130
    spread          = Column(Float)                         # e.g. -3.5 (home)
    spread_juice    = Column(Integer)                       # e.g. -110
    total_over_under= Column(Float)                         # e.g. 224.5
    total_juice     = Column(Integer)                       # e.g. -110
    # Line movement tracking
    opening_spread  = Column(Float)
    opening_total   = Column(Float)
    opening_home_ml = Column(Integer)
    # Public betting %
    home_bet_pct    = Column(Float)                         # % of public on home
    away_bet_pct    = Column(Float)
    over_bet_pct    = Column(Float)
    # Sharp money indicator
    sharp_action    = Column(String(20))                    # home / away / over / under / None
    # Timestamp (capture history of line movement)
    captured_at     = Column(DateTime, default=datetime.utcnow)

    game = relationship("Game", back_populates="odds")

    __table_args__ = (
        Index("idx_odds_game_book", "game_id", "sportsbook"),
    )


# ══════════════════════════════════════════════════════════════════════
#  PLAYER STATS (per game)
# ══════════════════════════════════════════════════════════════════════

class PlayerStats(Base):
    __tablename__ = "player_stats"

    id          = Column(Integer, primary_key=True)
    player_id   = Column(String(50), ForeignKey("players.player_id"))
    game_id     = Column(String(50), ForeignKey("games.game_id"))
    sport       = Column(String(10))
    season_year = Column(Integer)
    is_starter  = Column(Boolean, default=True)
    minutes     = Column(Float)
    # Universal
    raw_stats   = Column(JSON)   # Stores all sport-specific stats as JSON
    # NBA quick access columns
    points      = Column(Float)
    assists     = Column(Float)
    rebounds    = Column(Float)
    steals      = Column(Float)
    blocks      = Column(Float)
    turnovers   = Column(Float)
    fg_pct      = Column(Float)
    three_pt_pct= Column(Float)
    ft_pct      = Column(Float)
    plus_minus  = Column(Float)
    # NFL quick access
    passing_yards  = Column(Float)
    rushing_yards  = Column(Float)
    receiving_yards= Column(Float)
    touchdowns     = Column(Integer)
    interceptions  = Column(Integer)
    # MLB quick access
    hits        = Column(Integer)
    home_runs   = Column(Integer)
    rbi         = Column(Integer)
    era         = Column(Float)
    strikeouts  = Column(Integer)
    # NHL quick access
    goals       = Column(Integer)
    hockey_assists = Column(Integer)
    shots_on_goal  = Column(Integer)
    save_pct    = Column(Float)

    player = relationship("Player", back_populates="stats")
    game   = relationship("Game", back_populates="player_stats")

    __table_args__ = (
        UniqueConstraint("player_id", "game_id", name="uq_player_game"),
        Index("idx_stats_player", "player_id"),
        Index("idx_stats_game", "game_id"),
    )


# ══════════════════════════════════════════════════════════════════════
#  INJURY REPORTS
# ══════════════════════════════════════════════════════════════════════

class InjuryReport(Base):
    __tablename__ = "injury_reports"

    id              = Column(Integer, primary_key=True)
    player_id       = Column(String(50), ForeignKey("players.player_id"))
    sport           = Column(String(10))
    report_date     = Column(DateTime, default=datetime.utcnow)
    status          = Column(String(50))    # Out / Doubtful / Questionable / Probable / GTD
    injury_type     = Column(String(100))   # "Left knee soreness"
    body_part       = Column(String(50))
    game_id         = Column(String(50))    # Which game this applies to
    estimated_return= Column(String(100))   # "2-3 weeks" or specific date
    source          = Column(String(100))   # ESPN / Rotowire / Team Report
    notes           = Column(Text)
    captured_at     = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player", back_populates="injury_reports")

    __table_args__ = (
        Index("idx_injury_player", "player_id"),
        Index("idx_injury_date", "report_date"),
    )


# ══════════════════════════════════════════════════════════════════════
#  PLAYER CONTRACTS & INCENTIVE CLAUSES
# ══════════════════════════════════════════════════════════════════════

class PlayerContract(Base):
    __tablename__ = "player_contracts"

    id                  = Column(Integer, primary_key=True)
    player_id           = Column(String(50), ForeignKey("players.player_id"), unique=True)
    sport               = Column(String(10))
    # Contract basics
    total_value         = Column(Float)         # Total contract value in dollars
    years               = Column(Integer)
    annual_salary       = Column(Float)
    year_signed         = Column(Integer)
    expiration_year     = Column(Integer)
    contract_type       = Column(String(50))    # Max / Veteran / Rookie / etc.
    # Options & status
    has_player_option   = Column(Boolean, default=False)
    option_year         = Column(Integer)
    has_team_option     = Column(Boolean, default=False)
    no_trade_clause     = Column(Boolean, default=False)
    is_guaranteed       = Column(Boolean, default=True)
    # Incentive clauses — THIS IS THE BETTING EDGE
    incentives          = Column(JSON)
    # Example incentives JSON structure:
    # [
    #   {"type": "stats", "stat": "points_per_game", "threshold": 25.0,
    #    "bonus_amount": 2000000, "likely": true, "games_remaining": 12},
    #   {"type": "games_played", "threshold": 70, "bonus_amount": 500000}
    # ]
    incentive_summary   = Column(Text)          # Human-readable summary
    source_url          = Column(String(500))
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    player = relationship("Player", back_populates="contract")


# ══════════════════════════════════════════════════════════════════════
#  NEWS & SOFT DATA
# ══════════════════════════════════════════════════════════════════════

class NewsArticle(Base):
    __tablename__ = "news_articles"

    id              = Column(Integer, primary_key=True)
    sport           = Column(String(10))
    source          = Column(String(100))       # ESPN / The Athletic / Rotowire
    title           = Column(String(500))
    content         = Column(Text)
    url             = Column(String(1000), unique=True)
    published_at    = Column(DateTime)
    # AI-parsed fields
    mentioned_players = Column(JSON)            # ["LeBron James", "Anthony Davis"]
    mentioned_teams   = Column(JSON)
    sentiment_score   = Column(Float)           # -1.0 (negative) to 1.0 (positive)
    relevance_tags    = Column(JSON)            # ["injury", "trade", "lineup", "motivation"]
    betting_impact    = Column(String(50))      # high / medium / low / none
    captured_at       = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_news_sport", "sport"),
        Index("idx_news_published", "published_at"),
    )


class SocialPost(Base):
    __tablename__ = "social_posts"

    id                = Column(Integer, primary_key=True)
    sport             = Column(String(10))
    platform          = Column(String(20))          # reddit / twitter / instagram
    source_name       = Column(String(100))         # subreddit or @handle
    post_id           = Column(String(100), unique=True)
    author            = Column(String(100))
    content           = Column(Text)
    url               = Column(String(1000))
    # Engagement
    upvotes           = Column(Integer, default=0)
    comments          = Column(Integer, default=0)
    is_verified_source= Column(Boolean, default=False)  # Known beat reporter?
    # AI-parsed fields
    mentioned_players = Column(JSON)
    mentioned_teams   = Column(JSON)
    sentiment_score   = Column(Float)
    relevance_tags    = Column(JSON)
    betting_impact    = Column(String(50))
    published_at      = Column(DateTime)
    captured_at       = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_social_sport_platform", "sport", "platform"),
        Index("idx_social_published", "published_at"),
    )


# ══════════════════════════════════════════════════════════════════════
#  HEAD-TO-HEAD MATCHUP HISTORY
# ══════════════════════════════════════════════════════════════════════

class TeamMatchupHistory(Base):
    __tablename__ = "team_matchup_history"

    id              = Column(Integer, primary_key=True)
    sport           = Column(String(10))
    team_a_id       = Column(String(50))
    team_b_id       = Column(String(50))
    season_year     = Column(Integer)
    # Aggregated stats for this matchup
    games_played    = Column(Integer)
    team_a_wins     = Column(Integer)
    team_b_wins     = Column(Integer)
    avg_total_score = Column(Float)
    avg_spread      = Column(Float)
    ats_record_a    = Column(String(20))    # Against-the-spread record: "4-2"
    ats_record_b    = Column(String(20))
    over_record     = Column(String(20))    # "3-3" (over hit 3 of 6)
    updated_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("sport", "team_a_id", "team_b_id", "season_year",
                         name="uq_matchup_season"),
    )


class PlayerMatchupHistory(Base):
    __tablename__ = "player_matchup_history"

    id                  = Column(Integer, primary_key=True)
    sport               = Column(String(10))
    player_id           = Column(String(50))
    opponent_team_id    = Column(String(50))
    # Defender matchup (for NBA player props)
    primary_defender_id = Column(String(50))
    season_year         = Column(Integer)
    games_played        = Column(Integer)
    avg_stats           = Column(JSON)      # Average stats in this matchup
    over_prop_hit_rate  = Column(Float)     # % of time player exceeded typical prop line
    updated_at          = Column(DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════
#  BET SIGNALS (AI Output)
# ══════════════════════════════════════════════════════════════════════

class BetSignal(Base):
    __tablename__ = "bet_signals"

    id              = Column(Integer, primary_key=True)
    sport           = Column(String(10))
    game_id         = Column(String(50))
    generated_at    = Column(DateTime, default=datetime.utcnow)
    # Bet details
    bet_type        = Column(String(50))    # spread / moneyline / total / player_prop
    bet_selection   = Column(String(200))   # "Lakers -3.5" or "LeBron over 27.5 pts"
    confidence      = Column(Float)         # 1-10 score from AI
    recommended_units = Column(Float)       # 0.5 / 1 / 2 units
    # AI reasoning
    reasoning       = Column(Text)          # Full AI explanation
    key_factors     = Column(JSON)          # ["Injury to starter", "Line moved 2 pts"]
    red_flags       = Column(JSON)          # ["Player posted late on Instagram"]
    data_sources    = Column(JSON)          # What data was used
    # Result tracking
    result          = Column(String(20))    # win / loss / push / pending
    actual_line     = Column(Float)
    closing_line    = Column(Float)
    clv             = Column(Float)         # Closing line value (positive = good)

    __table_args__ = (
        Index("idx_signals_game", "game_id"),
        Index("idx_signals_sport_date", "sport", "generated_at"),
    )


# ══════════════════════════════════════════════════════════════════════
#  PLAYER PROP EDGES
# ══════════════════════════════════════════════════════════════════════

class PropEdgeDB(Base):
    __tablename__ = "prop_edges"

    id                = Column(Integer, primary_key=True)
    sport             = Column(String(10), nullable=False)
    game_id           = Column(String(50))
    player_name       = Column(String(100), nullable=False)
    team              = Column(String(100))
    opponent          = Column(String(100))
    prop_type         = Column(String(50))   # player_points / pitcher_strikeouts etc
    prop_label        = Column(String(50))   # Points / Strikeouts etc
    # Best lines across books
    best_over_line    = Column(Float)
    best_over_odds    = Column(Integer)
    best_over_book    = Column(String(50))
    best_under_line   = Column(Float)
    best_under_odds   = Column(Integer)
    best_under_book   = Column(String(50))
    line_spread       = Column(Float)        # Difference between highest/lowest line
    num_books         = Column(Integer)
    # All lines as JSON
    all_lines         = Column(JSON)
    # Player history
    player_avg        = Column(Float)
    recent_avg        = Column(Float)
    vs_opponent_avg   = Column(Float)
    # Edge
    edge_direction    = Column(String(10))   # over / under / none
    edge_strength     = Column(Float)        # 0-10
    edge_reason       = Column(Text)
    web_context       = Column(Text)
    # Metadata
    is_best_bet       = Column(Boolean, default=False)
    result            = Column(String(20), default="pending")
    generated_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_props_sport_date", "sport", "generated_at"),
        Index("idx_props_player", "player_name"),
    )


# ══════════════════════════════════════════════════════════════════════
#  DATABASE CONNECTION HELPERS
# ══════════════════════════════════════════════════════════════════════

def get_engine():
    return create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()

def create_all_tables():
    engine = get_engine()
    Base.metadata.create_all(engine)
    print("✅ All database tables created successfully.")
