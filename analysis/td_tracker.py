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
import json
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from loguru import logger
from config.settings import ANTHROPIC_API_KEY

MODEL = "claude-sonnet-4-6"


def _parse_td_plays(text):
    """Pull the TD_JSON block into structured, graded TD picks."""
    m = re.search(r'TD_JSON:\s*(\[.*\])', text, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(1))
    except Exception:
        return []
    out = []
    for p in arr:
        try:
            out.append({
                "player": str(p.get("player", "")).strip(),
                "pos": str(p.get("pos", "")).strip(),
                "verdict": str(p.get("verdict", "")).strip().title(),
                "confidence": int(float(p.get("confidence", 0))),
                "reason": str(p.get("reason", "")).strip(),
            })
        except Exception:
            continue
    return out


def _web(query, extraction):
    try:
        from analysis.game_analysis import _web_context
        return _web_context(query, extraction)
    except Exception as e:
        logger.debug(f"[TDTracker] web failed: {e}")
        return "(no recent web context available)"


def project_touchdowns(game, edge_plays=None, ranker=None) -> dict:
    """
    `game` is an NFLGame. `edge_plays` is the optional list of
    (name, prop_label, hit_rate, tier) tuples from analyze_nfl_game — pass it
    when available so goal-line volume is grounded in the model's data.
    `ranker` (optional) unlocks REAL ESPN TD data — per-player TD rate + a
    data-based anytime-TD probability — which anchors the whole board.
    Returns {"matchup":..., "board": <markdown>, "td_data": [rows]}.
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

    # Real TD data from ESPN game logs (anchors the estimate)
    td_rows, data_md = [], ""
    if ranker is not None:
        try:
            from analysis.td_data import game_td_data, data_table_md
            td_rows = game_td_data(game, ranker)
            data_md = data_table_md(td_rows, top=12)
        except Exception as e:
            logger.debug(f"[TDTracker] TD data failed: {e}")
            data_md = "(TD data unavailable — estimating from web context)"
    else:
        data_md = "(no TD data — estimating from web context)"

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

REAL TD DATA (from ESPN game logs — TD/gm is actual TDs per game, P(any) is
the data-based anytime-TD probability from their real scoring rate. START from
these numbers; adjust up/down only for matchup, injuries, and role changes):
{data_md}

MODEL VOLUME (rushing/receiving volume our data surfaced — high rush volume
often signals goal-line work):
{plays_txt}

WEB CONTEXT (red-zone roles, pace, likely scorers):
{web}

Produce a TD BOARD in exactly this shape:

**{game.away_team}** — est. offensive plays: <n>, expected TDs: <n>
1. Player (POS) — ~XX% anytime TD — one-line why (anchor to the data P(any), then goal-line role / RZ targets / matchup)
2. Player (POS) — ~XX% — why
(top 3-4 scorers)

**{game.home_team}** — est. offensive plays: <n>, expected TDs: <n>
1. Player (POS) — ~XX% — why
...

Then:
**BEST TD BET:** <one line>
**CAUTION:** <one line — who's TD-dependent or splitting goal-line work>

Anchor each % to the REAL TD DATA P(any) above; move off it only with a stated
reason (matchup funnel, injury vacating goal-line work, role change). Estimate
plays and expected TDs from pace + points. No hype. Keep the board under 250 words.

After the board, output on its own line exactly this and nothing after it:
TD_JSON: [{{"player":"Full Name","pos":"RB","verdict":"Play|Lean|Pass","confidence":<0-100>,"reason":"<=12 words"}}]
Rules for TD_JSON:
- Include every scorer you listed for both teams.
- confidence = your anytime-TD probability, anchored to the REAL TD DATA P(any),
  adjusted for matchup / injury / role.
- Any player OUT / inactive / not playing = "Pass", confidence 0.
- Valid JSON only, one array, no trailing text."""

    try:
        from analysis.system_prompt import MASTER_SYSTEM_PROMPT
        sysprompt = MASTER_SYSTEM_PROMPT
    except Exception:
        sysprompt = "You are a rigorous, honest sports betting analyst."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=1000, system=sysprompt,
            messages=[{"role": "user", "content": prompt}])
        board = resp.content[0].text
    except Exception as e:
        board = f"TD projection failed: {e}"

    # Split the graded TD picks out of the board
    td_plays = _parse_td_plays(board)
    board = re.sub(r'\n*TD_JSON:\s*\[.*\]\s*$', '', board, flags=re.S).strip()

    # Prepend the real data table so it's shown and saved with the board
    if td_rows and not board.startswith("TD projection failed"):
        board = ("**📊 Real TD data (ESPN game logs):**\n\n"
                 + data_md + "\n\n---\n\n" + board)

    return {"matchup": matchup, "board": board,
            "td_plays": td_plays, "td_data": td_rows}
