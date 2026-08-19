"""
analysis/prompt_builder.py

Turns a GameContext into a structured prompt for the AI.
Key design principles:
  - Never hide missing data. If we don't have it, say so.
  - Confidence must be EARNED by data, not assumed.
  - The AI is told explicitly what data is available vs missing.
  - No hallucination of stats we don't have.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.context_builder import GameContext, TeamContext


def _format_team_section(team: TeamContext, label: str) -> str:
    """Format one team's data honestly — flagging gaps."""
    lines = [f"## {label}: {team.name} ({'HOME' if team.is_home else 'AWAY'})"]

    # Record
    if team.wins or team.losses:
        lines.append(f"Record: {team.wins}-{team.losses}")
    else:
        lines.append("Record: NOT AVAILABLE")

    # Rest
    lines.append(f"Days of rest: {team.days_rest}")
    if team.is_back_to_back:
        lines.append("⚠️ BACK-TO-BACK GAME — fatigue factor applies")

    # Rankings
    if team.offense_rank:
        lines.append(f"Offense rank: #{team.offense_rank} | Defense rank: #{team.defense_rank}")
    else:
        lines.append("Offensive/defensive rankings: NOT AVAILABLE")

    # Recent form
    if team.last_10_record:
        lines.append(f"Last 10 games: {team.last_10_record}")
    else:
        lines.append("Recent form: NOT AVAILABLE")

    # Head to head
    if team.h2h_last_5:
        lines.append(f"H2H last 5: {team.h2h_last_5}")
    else:
        lines.append("Head-to-head history: NOT AVAILABLE")

    # Injuries
    if team.injured_out:
        lines.append(f"⛔ OUT: {', '.join(team.injured_out)}")
    else:
        lines.append("Players OUT: None confirmed (verify before betting)")

    if team.injured_questionable:
        lines.append(f"⚠️ QUESTIONABLE: {', '.join(team.injured_questionable)}")

    # Key players with stats
    lines.append("\nKey players:")
    active_players = [p for p in team.players
                      if p.status not in ["Out", "IR"]][:8]

    for p in active_players:
        player_line = f"  {p.name} ({p.position})"

        if p.recent_stats:
            s = p.recent_stats
            player_line += (f" — Last {s.get('games','?')} games avg: "
                           f"{s.get('points','?')} pts, "
                           f"{s.get('rebounds','?')} reb, "
                           f"{s.get('assists','?')} ast")
        else:
            player_line += " — Recent stats: NOT AVAILABLE"

        if p.vs_opponent:
            v = p.vs_opponent
            player_line += (f" | vs this opponent ({v.get('games_vs_opponent','?')} games): "
                           f"{v.get('avg_points','?')} pts avg")

        if p.has_active_incentive and p.contract_incentives:
            player_line += " | ⚡ HAS ACTIVE CONTRACT INCENTIVE CLAUSE"

        if p.injury_detail:
            player_line += f" | STATUS: {p.status} ({p.injury_detail})"

        if p.social_mentions:
            player_line += f" | 🔴 FLAGGED IN RECENT SOCIAL MEDIA"

        lines.append(player_line)

    if not active_players:
        lines.append("  Player data: NOT AVAILABLE")

    return "\n".join(lines)


def _format_odds_section(odds, sport: str) -> str:
    """Format odds with line movement analysis."""
    lines = ["## BETTING LINES"]

    if odds.spread is not None:
        lines.append(f"Spread: {odds.spread:+.1f} (home)")
        if odds.opening_spread is not None and odds.spread != odds.opening_spread:
            lines.append(f"  Opened: {odds.opening_spread:+.1f} → Now: {odds.spread:+.1f} "
                        f"(moved {odds.spread_moved:+.1f})")
            if odds.significant_move:
                lines.append(f"  ⚡ SIGNIFICANT LINE MOVE: {odds.movement_direction}")
        else:
            lines.append("  Line movement: Stable (no significant movement)")
    else:
        lines.append("Spread: NOT AVAILABLE")

    if odds.total is not None:
        lines.append(f"Total (O/U): {odds.total}")
        if odds.total_moved:
            lines.append(f"  Total moved: {odds.total_moved:+.1f} from open")
    else:
        lines.append("Total: NOT AVAILABLE")

    if odds.home_moneyline:
        lines.append(f"Moneyline: Home {odds.home_moneyline:+d} | Away {odds.away_moneyline:+d}")
    else:
        lines.append("Moneyline: NOT AVAILABLE")

    if odds.book_lines:
        lines.append(f"Books tracked: {len(odds.book_lines)} sportsbooks")

    return "\n".join(lines)


def build_analysis_prompt(ctx: GameContext) -> str:
    """
    Build the full analysis prompt from a GameContext.
    Honest about data gaps — never asks AI to assume missing info.
    """

    # Data quality assessment
    data_quality_flags = []
    if not ctx.odds.spread:
        data_quality_flags.append("No odds data available")
    if not ctx.home_team.players:
        data_quality_flags.append("No player data for home team")
    if not ctx.away_team.players:
        data_quality_flags.append("No player data for away team")
    if not ctx.recent_news:
        data_quality_flags.append("No recent news found")
    if not ctx.home_team.last_10_record:
        data_quality_flags.append("No recent form data")
    if not ctx.home_team.h2h_last_5:
        data_quality_flags.append("No head-to-head history")

    data_quality = "HIGH" if len(data_quality_flags) == 0 else \
                   "MEDIUM" if len(data_quality_flags) <= 2 else "LOW"

    home = ctx.home_team
    away = ctx.away_team

    prompt = f"""Analyze this game using the full structured framework. Apply data tier classification
to every piece of evidence. A NO BET recommendation is valid and often correct.

DATA QUALITY NOTE: Items marked "NOT AVAILABLE" must be labeled as missing in your analysis —
do not estimate or assume. Low data availability = lower confidence score = smaller units.

SHARP LINE MOVEMENT IS TIER 1 SIGNAL. Public line movement is noise. Know the difference.

=============================================================
GAME: {away.name} @ {home.name}
SPORT: {ctx.sport}
DATE: {ctx.game_date.strftime('%A, %B %d, %Y %I:%M %p')} ET
VENUE: {ctx.venue_name or 'NOT AVAILABLE'}{f' (altitude: {ctx.altitude_ft} ft)' if ctx.altitude_ft else ''}
=============================================================

DATA QUALITY ASSESSMENT: {data_quality}
{f'Missing data: {"; ".join(data_quality_flags)}' if data_quality_flags else 'All key data available'}

{_format_odds_section(ctx.odds, ctx.sport)}

{_format_team_section(away, f"AWAY TEAM")}

{_format_team_section(home, f"HOME TEAM")}

## ENVIRONMENT
Venue: {ctx.venue_name or 'Unknown'}
{f'Temperature: {ctx.temperature}°F' if ctx.temperature else ''}
{f'Weather: {ctx.weather_desc}' if ctx.weather_desc else ''}
{f'Referees: {", ".join(ctx.referee_names)}' if ctx.referee_names else 'Referee assignments: NOT AVAILABLE'}

## RECENT NEWS (last 48 hours)
{chr(10).join(f'  • {n}' for n in ctx.recent_news[:15]) if ctx.recent_news else '  No relevant news found'}

## SOCIAL MEDIA / RUMORS (last 6 hours)
{chr(10).join(f'  • {s}' for s in ctx.social_buzz[:10]) if ctx.social_buzz else '  No relevant social posts found'}

## HIGH-IMPACT ALERTS
{chr(10).join(f'  🚨 {a}' for a in ctx.high_impact_alerts) if ctx.high_impact_alerts else '  No high-impact alerts'}

=============================================================
YOUR ANALYSIS TASK
=============================================================

Provide your analysis using the full structured framework:

1. QUICK SUMMARY
[1-2 sentences. Bottom-line call in plain language.]

2. HARD DATA SNAPSHOT (Tier 1)
[Season baseline vs. recent-form trend for key players. Label each separately.]
[State which stats are verified vs. estimated/unavailable.]

3. CONTEXT ADJUSTMENTS (Tier 2)
[Opponent strength rank, home/away, rest days, travel, altitude, matchup history.]
[If adjustment impossible due to missing data, say so.]

4. SOFT/SPECULATIVE SIGNALS (Tier 3)
[Social media sentiment, rumors, narrative. MUST be clearly labeled Tier 3.]
[Sentiment-vs-data divergence check: do public narratives match the data?]

5. INJURY IMPACT
[Status: OUT / DOUBTFUL / QUESTIONABLE / PROBABLE / LIMITED for each relevant player.]
[Ripple effects: who sees more usage if a key player is out?]

6. COUNTER-CASE
[Strongest reasonable argument for the opposite outcome.]
[What would have to be true for that to happen?]

7. PREDICTION & CONFIDENCE
Type: [spread / moneyline / total / player_prop / NO BET]
Selection: [exact bet or "NO BET"]
Probability: [XX-XX% likely]
Confidence Score: [1-10]
Units: [0 = no bet | 0.5 = very small | 1 = standard | 2 = strong | 3 = max — only 8+ confidence with full Tier 1 data]
Edge vs. Consensus: [Does this diverge from public expectation? Why?]

8. WATCHLIST
[2-3 specific triggers that would change this call before game time.]

9. SELF-AUDIT
[Which tier did the conclusion rely on most? What is the single lowest-confidence assumption?]
"""

    return prompt


def build_pregame_summary(ctx: GameContext) -> str:
    """
    Shorter summary prompt for quick pre-game checks.
    Used when game is <2 hours away.
    """
    home = ctx.home_team
    away = ctx.away_team

    return f"""Quick pre-game check: {away.name} @ {home.name} ({ctx.sport})

Current line: Spread {ctx.odds.spread:+.1f} | Total {ctx.odds.total}
Line moved: {ctx.odds.spread_moved:+.1f} spread, {ctx.odds.total_moved:+.1f} total

URGENT items to check:
- Injury updates in last 2 hours: {', '.join(ctx.high_impact_alerts) if ctx.high_impact_alerts else 'None flagged'}
- Starting lineup confirmed: {'Check team sources — NOT verified' }
- Any last-minute scratches: {'Check injury report NOW'}

Social media last 2 hours:
{chr(10).join(f'• {s[:200]}' for s in ctx.social_buzz[:5]) if ctx.social_buzz else 'Nothing flagged'}

Does anything here change the original analysis? Answer YES or NO and explain why."""
