"""
analysis/ai_engine.py

The core AI analysis engine.
Takes a GameContext, sends it to Claude, parses the structured
response into a BetSignal, and saves it to the database.

Design principles:
- Honest confidence — never inflates scores
- Parses AI output strictly — no hallucinated fields
- Tracks data quality so you know HOW MUCH to trust each signal
- Saves full reasoning for review
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import re
import anthropic
from datetime import datetime
from loguru import logger
from dataclasses import dataclass, field
from typing import Optional

from analysis.context_builder import GameContext, ContextBuilder
from analysis.prompt_builder import build_analysis_prompt, build_pregame_summary
from database.models import get_session, BetSignal, Game
from config.settings import ANTHROPIC_API_KEY, SUPPORTED_SPORTS

# Use Sonnet for cost efficiency — smart enough for this task
MODEL = "claude-sonnet-4-6"


@dataclass
class ParsedBetSignal:
    """Structured output from the AI analysis."""
    game_id:            str
    sport:              str
    # Core signal
    bet_type:           str = "none"        # spread / moneyline / total / player_prop / none
    bet_selection:      str = "NO BET"
    confidence:         float = 0.0         # 1-10
    recommended_units:  float = 0.0         # 0 / 0.5 / 1 / 2 / 3
    # Scores
    data_confidence:    float = 0.0         # How much data did we have?
    team_total_score:   float = 0.0
    # Analysis text
    reasoning:          str = ""
    key_factors:        list = field(default_factory=list)
    red_flags:          list = field(default_factory=list)
    player_props:       list = field(default_factory=list)
    line_movement_note: str = ""
    final_note:         str = ""
    # Meta
    raw_response:       str = ""
    generated_at:       datetime = field(default_factory=datetime.utcnow)
    is_no_bet:          bool = True


def _parse_score(text: str, label: str) -> float:
    """Extract a numeric score from AI response text."""
    pattern = rf"{re.escape(label)}[:\s]+([0-9]+(?:\.[0-9]+)?)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


def _parse_section(text: str, section_name: str) -> str:
    """Extract a section from the structured AI response."""
    pattern = rf"---{re.escape(section_name)}---\s*(.*?)(?=---|\Z)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _parse_units(text: str) -> float:
    """Parse recommended unit size from AI response."""
    units_section = _parse_section(text, "RECOMMENDED BET")
    unit_match = re.search(r"units?[:\s]+([0-9]+(?:\.[0-9]+)?)", units_section, re.IGNORECASE)
    if unit_match:
        try:
            val = float(unit_match.group(1))
            # Cap at 3 units max — safety guardrail
            return min(val, 3.0)
        except ValueError:
            pass
    return 0.0


def _parse_bet_type(text: str) -> tuple[str, str]:
    """Parse bet type and selection from AI response."""
    rec_section = _parse_section(text, "RECOMMENDED BET")

    # Check for NO BET
    if "NO BET" in rec_section.upper():
        return "none", "NO BET"

    # Parse type
    type_match = re.search(r"type[:\s]+(spread|moneyline|total|player.?prop|no.?bet)",
                           rec_section, re.IGNORECASE)
    bet_type = type_match.group(1).lower().replace(" ", "_") if type_match else "none"

    # Parse selection
    sel_match = re.search(r"selection[:\s]+(.+?)(?:\n|$)", rec_section, re.IGNORECASE)
    selection = sel_match.group(1).strip() if sel_match else "NO BET"

    if "NO BET" in selection.upper():
        return "none", "NO BET"

    return bet_type, selection


def parse_ai_response(response_text: str, game_id: str, sport: str) -> ParsedBetSignal:
    """
    Parse the structured AI response into a ParsedBetSignal.
    Strict parsing — if a field isn't found, it stays at default (empty/zero).
    """
    signal = ParsedBetSignal(game_id=game_id, sport=sport)
    signal.raw_response = response_text

    # Data confidence score
    data_section = _parse_section(response_text, "DATA CONFIDENCE")
    signal.data_confidence = _parse_score(data_section, "Score")

    # Team total score
    team_section = _parse_section(response_text, "TEAM TOTAL ASSESSMENT")
    signal.team_total_score = _parse_score(team_section, "Score")

    # Line movement note
    signal.line_movement_note = _parse_section(response_text, "LINE MOVEMENT ANALYSIS")

    # Player props
    props_section = _parse_section(response_text, "PLAYER PROP EDGES")
    if "INSUFFICIENT" not in props_section.upper() and props_section:
        # Parse each prop line
        for line in props_section.split("\n"):
            line = line.strip()
            if "|" in line and len(line) > 10:
                signal.player_props.append(line)

    # Red flags
    flags_section = _parse_section(response_text, "RED FLAGS")
    if flags_section:
        for line in flags_section.split("\n"):
            line = line.strip("- •*").strip()
            if line and len(line) > 5:
                signal.red_flags.append(line)

    # Recommended bet
    signal.bet_type, signal.bet_selection = _parse_bet_type(response_text)
    signal.is_no_bet = (signal.bet_selection == "NO BET" or signal.bet_type == "none")
    signal.recommended_units = _parse_units(response_text)

    # Confidence
    rec_section = _parse_section(response_text, "RECOMMENDED BET")
    signal.confidence = _parse_score(rec_section, "Confidence")

    # Reasoning (from recommended bet section)
    reasoning_match = re.search(r"reasoning[:\s]+(.+?)(?=confidence|units|\Z)",
                                rec_section, re.DOTALL | re.IGNORECASE)
    if reasoning_match:
        signal.reasoning = reasoning_match.group(1).strip()[:1000]

    # Key factors
    factors_match = re.search(r"key factors?[:\s]+(.+?)(?=missing|\Z)",
                               team_section, re.DOTALL | re.IGNORECASE)
    if factors_match:
        for line in factors_match.group(1).split("\n"):
            line = line.strip("- •*").strip()
            if line and len(line) > 5:
                signal.key_factors.append(line)

    # Final note
    signal.final_note = _parse_section(response_text, "FINAL NOTE")

    return signal


class AIEngine:
    """Runs AI analysis on games and generates bet signals."""

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set in .env file")
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.context_builder = ContextBuilder()

    def analyze_game(self, game_id: str) -> Optional[ParsedBetSignal]:
        """
        Full analysis pipeline for one game.
        Returns ParsedBetSignal or None if analysis fails.
        """
        logger.info(f"[AI] Starting analysis for game {game_id}...")

        # Build context
        ctx = self.context_builder.build(game_id)
        if not ctx:
            logger.error(f"[AI] Could not build context for {game_id}")
            return None

        # Build prompt
        prompt = build_analysis_prompt(ctx)

        # Call Claude
        try:
            from analysis.system_prompt import MASTER_SYSTEM_PROMPT
            logger.info(f"[AI] Sending to Claude: {ctx.away_team.name} @ {ctx.home_team.name}")
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=2500,
                system=MASTER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.content[0].text
            logger.info(f"[AI] Response received ({len(raw_text)} chars)")

        except Exception as e:
            logger.error(f"[AI] Claude API call failed: {e}")
            return None

        # Parse response
        signal = parse_ai_response(raw_text, game_id, ctx.sport)

        # Log summary
        if signal.is_no_bet:
            logger.info(f"[AI] {ctx.away_team.name} @ {ctx.home_team.name}: "
                       f"NO BET (data confidence: {signal.data_confidence}/10)")
        else:
            logger.info(f"[AI] ⚡ BET SIGNAL: {signal.bet_selection} | "
                       f"Confidence: {signal.confidence}/10 | "
                       f"Units: {signal.recommended_units}")
            if signal.red_flags:
                logger.warning(f"[AI] Red flags: {signal.red_flags}")

        # Save to database
        self._save_signal(signal, ctx)

        return signal

    def _save_signal(self, signal: ParsedBetSignal, ctx: GameContext):
        """Save bet signal to database."""
        db = get_session()
        try:
            db_signal = BetSignal(
                sport=signal.sport,
                game_id=signal.game_id,
                generated_at=signal.generated_at,
                bet_type=signal.bet_type,
                bet_selection=signal.bet_selection,
                confidence=signal.confidence,
                recommended_units=signal.recommended_units,
                reasoning=signal.reasoning,
                key_factors=signal.key_factors,
                red_flags=signal.red_flags,
                data_sources={
                    "has_odds":     ctx.odds.spread is not None,
                    "has_news":     len(ctx.recent_news) > 0,
                    "has_social":   len(ctx.social_buzz) > 0,
                    "has_injuries": (len(ctx.home_team.injured_out) +
                                    len(ctx.away_team.injured_out)) > 0,
                    "data_quality": signal.data_confidence,
                },
                result="pending",
            )
            db.add(db_signal)
            db.commit()
            logger.info(f"[AI] ✅ Signal saved to database.")
        except Exception as e:
            db.rollback()
            logger.error(f"[AI] Failed to save signal: {e}")
        finally:
            db.close()

    def analyze_todays_games(self, sport: str) -> list[ParsedBetSignal]:
        """Analyze all of today's games for a sport."""
        db = get_session()
        try:
            today = datetime.utcnow().date()
            games = (db.query(Game)
                     .filter(Game.sport == sport,
                             Game.status == "Scheduled")
                     .all())

            if not games:
                logger.info(f"[AI] No scheduled {sport} games found for today.")
                return []

            logger.info(f"[AI] Analyzing {len(games)} {sport} games...")
            signals = []
            for game in games:
                signal = self.analyze_game(game.game_id)
                if signal:
                    signals.append(signal)

            return signals
        finally:
            db.close()

    def analyze_all_sports(self) -> dict:
        """Run analysis across all sports."""
        results = {}
        for sport in SUPPORTED_SPORTS:
            signals = self.analyze_todays_games(sport)
            bets = [s for s in signals if not s.is_no_bet]
            results[sport] = {
                "games_analyzed": len(signals),
                "bets_recommended": len(bets),
                "signals": signals,
            }
            logger.info(f"[AI] {sport}: {len(signals)} analyzed, "
                       f"{len(bets)} bets recommended")
        return results

    def analyze_single_game_by_teams(self, home_team_name: str,
                                      away_team_name: str,
                                      sport: str) -> Optional[ParsedBetSignal]:
        """
        Analyze a specific game by team names.
        Used for manual analysis from the dashboard.
        """
        db = get_session()
        try:
            from database.models import Team
            home = db.query(Team).filter(
                Team.sport == sport,
                Team.name.ilike(f"%{home_team_name}%")
            ).first()
            away = db.query(Team).filter(
                Team.sport == sport,
                Team.name.ilike(f"%{away_team_name}%")
            ).first()

            if not home or not away:
                logger.error(f"[AI] Could not find teams: {home_team_name} vs {away_team_name}")
                return None

            game = (db.query(Game)
                    .filter(Game.home_team_id == home.team_id,
                            Game.away_team_id == away.team_id,
                            Game.status == "Scheduled")
                    .order_by(Game.game_date.asc())
                    .first())

            if not game:
                logger.warning(f"[AI] No scheduled game found for "
                              f"{away_team_name} @ {home_team_name}")
                return None

            return self.analyze_game(game.game_id)
        finally:
            db.close()
