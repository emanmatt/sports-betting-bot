"""
analysis/game_analysis.py

Per-game Claude analysis — turns the model's edge data + injuries + live
news + team/scheme matchup into a framework-driven writeup for each game
(not a stats table).

Uses the Anthropic API (your key) + MASTER_SYSTEM_PROMPT framework.
No OddsAPI credits needed. One Claude call + two web searches per game;
results cached by the caller so re-viewing doesn't re-spend.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from loguru import logger
from config.settings import ANTHROPIC_API_KEY

MODEL = "claude-sonnet-4-6"


def _web_context(query: str, extraction_prompt: str) -> str:
    try:
        from data_ingestion.soft.web_search import WebSearchEngine
        ws = WebSearchEngine()
        findings = ws.search_and_extract(query, extraction_prompt)
        if hasattr(ws, "format_findings_for_prompt"):
            try:
                return ws.format_findings_for_prompt(findings)
            except Exception:
                pass
        return str(findings)[:2500]
    except Exception as e:
        logger.debug(f"[GameAnalysis] web search failed: {e}")
        return "(no recent web context available)"


def _team_matchup_context(matchup: str, home: str, away: str) -> str:
    """Offensive/defensive identity of both teams + the scheme funnel."""
    return _web_context(
        f"{away} vs {home} NFL 2026 team offense defense rankings run pass "
        f"points per game yards allowed",
        f"For {matchup}, summarize each team plainly:\n"
        f"(1) OFFENSE — run-heavy or pass-heavy, pace/plays, points per game, "
        f"and their biggest offensive strength.\n"
        f"(2) DEFENSE — rush-defense rank and pass-defense rank (yards and "
        f"points allowed), and whether they are stronger against the run or "
        f"the pass.\n"
        f"(3) THE MATCHUP — which side's offensive strength meets the other's "
        f"defensive weakness (a 'funnel' spot), e.g. a weak run defense facing "
        f"a run-first offense funnels volume to the backs.\n"
        f"Use current-season ranks where available, else recent form. "
        f"Concise, factual, no betting advice.")


def analyze_nfl_game(game, ranker) -> dict:
    """
    Analyze one NFL game. `game` is an NFLGame; `ranker` an NFLRanker.
    Returns {"matchup":..., "writeup":..., "edge_plays":[...]}.
    """
    matchup = f"{game.away_team} @ {game.home_team}"

    # 1. Gather the model's edge plays (A/B board) for both teams
    edge_plays = []
    for team_id, team_name, opp_name in [
        (game.home_team_id, game.home_team, game.away_team),
        (game.away_team_id, game.away_team, game.home_team),
    ]:
        try:
            if ranker.inactives:
                ranker.inactives.load_team(team_id)
            for player in ranker.nfl.get_team_roster(team_id):
                edge_plays.extend(
                    ranker.rank_player(player, team_name, opp_name, matchup))
        except Exception:
            continue
    edge_plays.sort(key=lambda x: x.score, reverse=True)
    top = edge_plays[:8]

    # 2. Format the edge data for the prompt
    plays_txt = ""
    for p in top:
        inj = f" [{p.injury_flag}]" if getattr(p, "injury_flag", "") else ""
        plays_txt += (f"- {p.player_name} ({p.position}, {p.team}){inj}: "
                      f"{p.prop_label} — model hit {p.hit_rate:.0f}% over "
                      f"{p.games} games, avg {p.avg_value}, tier {p.tier}\n")
    if not plays_txt:
        plays_txt = "(no strong model plays surfaced for this game)"

    # 3. Team & scheme matchup profile (offense/defense identity + funnel)
    team_ctx = _team_matchup_context(matchup, game.home_team, game.away_team)

    # 4. Live web context (injuries, roles, matchup)
    web = _web_context(
        f"{matchup} NFL injuries inactives news preview 2026 week",
        f"For the game {matchup}: extract confirmed injuries/inactives, "
        f"backfield/target roles, key matchups, weather if outdoor, and any "
        f"news that affects rushing or receiving volume. Concise, factual.")

    # 5. Claude writeup
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Analyze this NFL game for a sharp bettor. Use the framework:
tier the data (hard vs contextual vs soft), give the strongest 1-3 plays
with real reasoning, a counter-case, and an honest confidence level.

GAME: {matchup}
Kickoff: {game.game_time}

TEAM & MATCHUP PROFILE (offensive/defensive identity, scheme funnel):
{team_ctx}

MODEL EDGE PLAYS (our data — rush-yard props are our proven edge; hit
rates are from recent games, prior-year early season. Judge whether each
player is trending UP or COOLING OFF from the hit rate + game count, and
whether the matchup profile above supports the volume):
{plays_txt}

LIVE WEB CONTEXT (injuries, roles, matchup news):
{web}

Write a tight game analysis (250-350 words):
1. THE LEAN — best 1-3 plays and WHY (role, volume, scheme matchup,
   recent player form)
2. TEAM MATCHUP — each team's offensive & defensive identity, and where the
   funnel points (does a weak run D vs a run-first offense push volume to the
   backs? is this a pass-funnel spot?). Tie the plays to it explicitly.
3. SITUATIONAL FACTORS — injuries opening/closing opportunity, game script,
   pace, who's in/out
4. COUNTER-CASE — what realistically makes the lean miss
5. CONFIDENCE — play it / lean / pass, and how confident

Ground everything in the data given. Do NOT invent stats. Flag thin data
plainly. Our rush-yard props are the edge; receiving/passing props have
been weaker — weight accordingly. No hype — an honest bettor's read."""

    try:
        from analysis.system_prompt import MASTER_SYSTEM_PROMPT
        sysprompt = MASTER_SYSTEM_PROMPT
    except Exception:
        sysprompt = "You are a rigorous, honest sports betting analyst."

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=900, system=sysprompt,
            messages=[{"role": "user", "content": prompt}])
        writeup = resp.content[0].text
    except Exception as e:
        writeup = f"Analysis failed: {e}"

    return {"matchup": matchup, "writeup": writeup,
            "edge_plays": [(p.player_name, p.prop_label, p.hit_rate, p.tier)
                           for p in top]}
