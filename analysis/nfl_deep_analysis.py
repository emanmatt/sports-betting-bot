"""
analysis/nfl_deep_analysis.py

Claude-written "deep analysis" for NFL plays — the Theo-Johnson-style
writeup. Takes a play from the board, gathers the player's stats +
injury context + a live web search, and has Claude build the CASE for
(or against) the play with situational reasoning.

Uses the Anthropic API (your key) — no OddsAPI credits needed.
Runs on a few plays you pick, to control API cost.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from loguru import logger
from config.settings import ANTHROPIC_API_KEY

MODEL = "claude-sonnet-4-6"  # matched to claude_tab; adjusted if different


def _gather_web_context(player_name: str, opponent: str) -> str:
    """Pull recent news/injury/depth-chart context via the web search helper."""
    try:
        from data_ingestion.soft.web_search import WebSearchEngine
        ws = WebSearchEngine()
        query = f"{player_name} NFL injury status role news 2026"
        extraction_prompt = (
            f"Extract anything relevant to betting a prop on {player_name} "
            f"vs {opponent}: injury/active status, depth-chart role, target "
            f"or touch share, recent usage, scheme/coaching notes, and any "
            f"teammate injuries that change his opportunity. Be concise and "
            f"factual; note if info is limited.")
        findings = ws.search_and_extract(query, extraction_prompt)
        if hasattr(ws, "format_findings_for_prompt"):
            try:
                return ws.format_findings_for_prompt(findings)
            except Exception:
                pass
        return str(findings)[:2000]
    except Exception as e:
        logger.debug(f"[DeepAnalysis] web search failed: {e}")
        return "(no recent web context available)"


def analyze_play(prop, sport="NFL") -> str:
    """
    Produce a situational writeup for one prop (a board play object).
    Expects: player_name, position, prop_label, prop_line, team,
             opponent, hit_rate, avg_value, games, data_season.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Stats context from the model
    stats = (
        f"Player: {prop.player_name} ({getattr(prop,'position','')}, {prop.team})\n"
        f"Prop: {prop.prop_label} (line {prop.prop_line})\n"
        f"Opponent: {prop.opponent}\n"
        f"Model hit rate: {prop.hit_rate:.0f}% over {prop.games} games "
        f"({getattr(prop,'data_season','')} data)\n"
        f"Average value: {prop.avg_value}\n"
    )
    injury = getattr(prop, "injury_flag", "") or "none reported"
    stats += f"Injury status: {injury}\n"

    # Live web context
    web = _gather_web_context(prop.player_name, prop.opponent)

    prompt = f"""You are analyzing a single NFL player prop for a sharp bettor.
Build a concise, honest case — like a professional capper's writeup.

THE PLAY:
{stats}

RECENT WEB CONTEXT (news, injuries, role):
{web}

Write a tight analysis (150-220 words) covering:
1. The CASE FOR the play — why it could hit (role, volume, matchup, scheme)
2. SITUATIONAL FACTORS — injuries opening opportunity, game script, pace,
   coverage tendencies, who's in/out around this player
3. THE RISK — what realistically makes it miss
4. HONEST VERDICT — lean (play it / pass / need more info) and confidence

Be specific and grounded. If the data is thin (early season, prior-year
only), say so plainly. Do NOT invent stats you don't have. Distinguish
last-season data from this-season. No hype — a real bettor's honest read."""

    try:
        from analysis.system_prompt import MASTER_SYSTEM_PROMPT
        sysprompt = MASTER_SYSTEM_PROMPT
    except Exception:
        sysprompt = "You are a rigorous, honest sports betting analyst."

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=sysprompt,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as e:
        return f"Analysis failed: {e}"
