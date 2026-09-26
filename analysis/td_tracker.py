"""
analysis/td_tracker.py

Touchdown-possibility tracker for a single NFL game. Estimates each team's
play volume and pace, then ranks the players most likely to score an anytime
touchdown — with a rough probability and the reason (goal-line role, red-zone
targets, scheme funnel). Uses the Anthropic key + web context. No OddsAPI.

Best run AFTER "Analyze This Game" for that matchup: the tab passes in the
model's volume data so the goal-line reads are grounded. Works standalone too
(web-only) if no analysis was run first.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from loguru import logger
from config.settings import ANTHROPIC_API_KEY

MODEL = "claude-sonnet-4-6"


def _web(query, extraction):
    try:
        from analysis.game_analysis import _web_context
        return _web_context(query, extraction)
    except Exception as e:
        logger.debug(f"[TDTracker] web failed: {e}")
        return "(no recent web context available)"


def project_touchdowns(game, edge_plays=None) -> dict:
    """
    `game` is an NFLGame. `edge_plays` is the optional list of
    (name, prop_label, hit_rate, tier) tuples from analyze_nfl_game — pass it
    when available so goal-line volume is grounded in the model's data.
    Returns {"matchup":..., "board": <markdown>}.
    """
    matchup = f"{game.away_team} @ {game.home_team}"

    plays_txt = ""
    if edge_plays:
        for tup in edge_plays[:10]:
            try:
                name, label, hr, tier = tup
                plays_txt += (f"- {name}: {label} "
                              f"(model {float(hr):.0f}%, tier {tier})\n")
            except Exception:
                continue
    if not plays_txt:
        plays_txt = "(no model volume supplied — infer scorers from web context)"

    web = _web(
        f"{matchup} NFL 2026 red zone touches goal line back red zone targets "
        f"anytime touchdown scorers plays per game pace points per game",
        f"For {matchup}: identify each team's likely touchdown scorers — the "
        f"goal-line/short-yardage runner, the red-zone target leader (WR/TE), "
        f"and any QB who runs near the goal line. Note each team's pace / "
        f"offensive plays per game and points per game. Concise, factual.")

    prompt = f"""You are projecting touchdowns for one NFL game for a bettor
weighing anytime-TD props. Be honest and grounded — TDs are noisy; do not
overstate certainty.

GAME: {matchup}
Kickoff: {game.game_time}

MODEL VOLUME (rushing/receiving volume our data surfaced — high rush volume
often signals goal-line work):
{plays_txt}

WEB CONTEXT (red-zone roles, pace, likely scorers):
{web}

Produce a TD BOARD in exactly this shape:

**{game.away_team}** — est. offensive plays: <n>, expected TDs: <n>
1. Player (POS) — ~XX% anytime TD — one-line why (goal-line role / RZ targets / matchup)
2. Player (POS) — ~XX% — why
(top 3-4 scorers)

**{game.home_team}** — est. offensive plays: <n>, expected TDs: <n>
1. Player (POS) — ~XX% — why
...

Then:
**BEST TD BET:** <one line>
**CAUTION:** <one line — who's TD-dependent or splitting goal-line work>

Estimate plays and expected TDs from pace + points. Base the % on red-zone
role and matchup, not hype. Keep it under 250 words."""

    try:
        from analysis.system_prompt import MASTER_SYSTEM_PROMPT
        sysprompt = MASTER_SYSTEM_PROMPT
    except Exception:
        sysprompt = "You are a rigorous, honest sports betting analyst."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=700, system=sysprompt,
            messages=[{"role": "user", "content": prompt}])
        board = resp.content[0].text
    except Exception as e:
        board = f"TD projection failed: {e}"

    return {"matchup": matchup, "board": board}
