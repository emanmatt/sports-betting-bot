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
import json
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from loguru import logger
from config.settings import ANTHROPIC_API_KEY

MODEL = "claude-sonnet-4-6"
# Cheap model for mechanical sub-tasks (extraction) — ~5x cheaper than Sonnet.
CHEAP_MODEL = "claude-haiku-4-5-20251001"


def _json_array(text):
    """Grab the first JSON array in text (tolerant of code fences / prose)."""
    m = re.search(r'\[.*\]', text, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        return []


def _normalize_plays(arr):
    out = []
    for p in arr or []:
        try:
            edge = p.get("edge", None)
            try:
                edge = int(float(edge)) if edge is not None and edge != "" else None
            except Exception:
                edge = None
            out.append({
                "player": str(p.get("player", "")).strip(),
                "prop": str(p.get("prop", "")).strip(),
                "verdict": str(p.get("verdict", "")).strip().title(),
                "confidence": int(float(p.get("confidence", 0))),
                "edge": edge,
                "reason": str(p.get("reason", "")).strip(),
            })
        except Exception:
            continue
    return out


def _extract_plays(client, writeup, plays_txt):
    """Second, short call: turn the finished writeup into structured graded
    plays. Isolated from the writeup so it can never be truncated off the end."""
    ex = ("From the NFL analysis below, output ONLY a JSON array (no prose, no "
          "code fence). Each item: {\"player\":\"\",\"prop\":\"\","
          "\"verdict\":\"Play|Lean|Pass\",\"confidence\":0-100,\"edge\":0,"
          "\"reason\":\"<=12 words\"}. "
          "`prop` = the RECOMMENDED line the analysis lands on (e.g. "
          "'64.5+ Rush Yards'), NOT the safe floor. `confidence` = the analysis's "
          "probability that line hits (%). `edge` = points of edge vs the book's "
          "implied odds (integer, e.g. 12; 0 if unknown). Include EVERY model edge "
          "play. A player who is OUT / inactive = verdict \"Pass\", confidence 0.\n\n"
          f"MODEL EDGE PLAYS:\n{plays_txt}\n\nANALYSIS:\n{writeup}")
    try:
        resp = client.messages.create(
            model=CHEAP_MODEL, max_tokens=700,
            messages=[{"role": "user", "content": ex}])
        return _normalize_plays(_json_array(resp.content[0].text))
    except Exception as e:
        logger.debug(f"[GameAnalysis] play extraction failed: {e}")
        return []


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
    name_to_id = {}
    for team_id, team_name, opp_name in [
        (game.home_team_id, game.home_team, game.away_team),
        (game.away_team_id, game.away_team, game.home_team),
    ]:
        try:
            if ranker.inactives:
                ranker.inactives.load_team(team_id)
            for player in ranker.nfl.get_team_roster(team_id):
                if isinstance(player, dict) and player.get("name") and player.get("id"):
                    name_to_id[player["name"]] = str(player["id"])
                edge_plays.extend(
                    ranker.rank_player(player, team_name, opp_name, matchup))
        except Exception:
            continue
    edge_plays.sort(key=lambda x: x.score, reverse=True)
    top = edge_plays[:8]

    # 2a. Real FanDuel + PrizePicks lines for this game (cached; ~6 credits once)
    by_book = {}
    try:
        from data_ingestion.official import book_lines as BL
        eid = BL.find_event_id(game.away_team, game.home_team)
        if eid:
            by_book = BL.fetch_focus_lines(eid)
    except Exception as e:
        logger.debug(f"[GameAnalysis] book lines unavailable: {e}")

    # 2b. Format the edge data for the prompt, annotated with the real book line
    plays_txt = ""
    for p in top:
        inj = f" [{p.injury_flag}]" if getattr(p, "injury_flag", "") else ""
        real = ""
        if by_book:
            try:
                mk = BL.market_from_prop(p.prop_label)
                if mk:
                    ls = BL.line_str_for(by_book, p.player_name, mk)
                    if ls:
                        real = f"  [BOOK: {ls}]"
            except Exception:
                pass
        plays_txt += (f"- {p.player_name} ({p.position}, {p.team}){inj}: "
                      f"{p.prop_label} — model hit {p.hit_rate:.0f}% over "
                      f"{p.games} games, avg {p.avg_value}, tier {p.tier}{real}\n")
    if not plays_txt:
        plays_txt = "(no strong model plays surfaced for this game)"

    # 2c. VALUE LADDER — real FanDuel lines (standard + alt) × our game-log hit
    #     rate at each, so the analysis can pick the best-VALUE line, not the safe floor.
    ladder_txt = ""
    if by_book:
        try:
            from analysis import prop_eval as PE
            seen = set()
            for p in top:
                mk = BL.market_from_prop(p.prop_label)
                if mk not in ("player_rush_yds", "player_receptions"):
                    continue
                key = (p.player_name, mk)
                if key in seen:
                    continue
                seen.add(key)
                pid = name_to_id.get(p.player_name)
                lad = BL.line_ladder(by_book, p.player_name, mk, "fanduel")
                if not pid or not lad:
                    continue
                vals = PE.game_values(pid, PE.STAT_KEY[mk])
                if not vals:
                    continue
                rungs = []
                for e in lad:
                    hr = PE.hit_rate(vals, e["line"])
                    imp = BL.american_to_prob(e.get("over"))
                    if hr is None:
                        continue
                    edge = (hr - imp) if imp is not None else None
                    od = e.get("over")
                    od_s = f"o{int(od):+d}" if od is not None else "o?"
                    edge_s = f", edge {edge*100:+.0f}" if edge is not None else ""
                    rungs.append(f"{e['line']:g} ({od_s}, hit {hr*100:.0f}%{edge_s})")
                if rungs:
                    lbl = "Rush Yds" if mk == "player_rush_yds" else "Receptions"
                    ladder_txt += (f"- {p.player_name} {lbl} (hit = cleared in "
                                   f"{len(vals)} games): " + " · ".join(rungs) + "\n")
        except Exception as e:
            logger.debug(f"[GameAnalysis] value ladder failed: {e}")

    # 3. ONE combined web search: injuries + team/scheme identity (cost saver)
    context = _web_context(
        f"{matchup} NFL 2026 injuries inactives team offense defense rankings preview",
        f"For {matchup}, concise and factual, two parts:\n"
        f"(A) INJURIES: confirmed injuries/inactives and role changes that affect "
        f"rushing or receiving volume (who's OUT, backfield/target roles, weather).\n"
        f"(B) TEAM IDENTITY: each team's offense (run vs pass, pace, points/game) "
        f"and defense rank vs the run and vs the pass, and where the funnel points "
        f"(e.g. weak run D vs a run-first offense = volume to the backs).")

    # 3b. Defense-vs-Position hard ranks (cached; built by build_dvp.py)
    dvp_block = ""
    try:
        from analysis.dvp_engine import load_dvp, dvp_summary
        _blob = load_dvp()
        if _blob:
            home_d = dvp_summary(_blob, game.home_team)  # faced by away offense
            away_d = dvp_summary(_blob, game.away_team)  # faced by home offense
            lines = [x for x in (away_d, home_d) if x]
            if lines:
                dvp_block = "\n".join(lines)
    except Exception as e:
        logger.debug(f"[GameAnalysis] DvP unavailable: {e}")

    # 4. Claude writeup
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Analyze this NFL game for a sharp bettor. Use the framework:
tier the data (hard vs contextual vs soft), give the strongest 1-3 plays
with real reasoning, a counter-case, and an honest confidence level.

GAME: {matchup}
Kickoff: {game.game_time}

DEFENSE VS POSITION (HARD matchup data — yards/receptions each defense allows
per game to RB/WR/TE; rank N/32 where 1 = softest/most allowed. This is the
funnel: a back facing a defense ranked top-5 softest vs RB rush is a real spot):
{dvp_block if dvp_block else "(DvP cache not built yet — run build_dvp.py)"}

MATCHUP & INJURY CONTEXT (injuries + team offensive/defensive identity + funnel):
{context}

MODEL EDGE PLAYS (our data — rush-yard props are our proven edge; hit
rates are from recent games, prior-year early season. Judge whether each
player is trending UP or COOLING OFF from the hit rate + game count, and
whether the matchup context above supports the volume. [BOOK: …] shows the
REAL main FanDuel/PrizePicks line):
{plays_txt}

VALUE LADDER (the REAL FanDuel lines — standard AND higher alternate lines —
with our actual hit rate at EACH line from the game log, plus the edge vs the
book's implied odds). DO NOT just take the safest low line. Recommend the line
with the BEST VALUE — the highest rung where hit% still clears the book's
implied odds with margin (positive edge) at a worthwhile payout. A 90%-safe
layup at -300 is often worse than a 62% line at +120:
{ladder_txt if ladder_txt else "(no ladder available for these players)"}

Write a tight game analysis (250-350 words):
1. THE LEAN — your best 1-3 plays. For EACH, state it like a bettor:
   "<Player> <recommended line>+ <stat> — ~XX% to hit, edge +Y vs the book's
   Z%". Pick the recommended line FROM THE VALUE LADDER (the best-value rung,
   not the safe floor). The XX% is your probability it hits after adjusting the
   raw ladder hit% for the factors (matchup/DvP, injuries, game script) — say
   which way the factors push it and why it would probably hit.
2. TEAM MATCHUP — each team's offensive & defensive identity, and where the
   funnel points (tie it to the DvP ranks and the plays explicitly).
3. SITUATIONAL FACTORS — injuries, game script, pace, who's in/out
4. COUNTER-CASE — what realistically makes the lean miss
5. CONFIDENCE — for each play: the recommended line, your hit %, the edge vs
   the book, and play it / lean / pass.

Ground everything in the data given. Do NOT invent stats. Lead with VALUE
(edge), not safety — a higher line with real edge beats a safe layup with none.
Flag thin data plainly. No hype — an honest bettor's read."""

    try:
        from analysis.system_prompt import MASTER_SYSTEM_PROMPT
        sysprompt = MASTER_SYSTEM_PROMPT
    except Exception:
        sysprompt = "You are a rigorous, honest sports betting analyst."

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=1400, system=sysprompt,
            messages=[{"role": "user", "content": prompt}])
        writeup = resp.content[0].text
    except Exception as e:
        writeup = f"Analysis failed: {e}"

    # Second call: extract the graded plays (can't be truncated off the writeup)
    plays = []
    if not writeup.startswith("Analysis failed"):
        plays = _extract_plays(client, writeup, plays_txt)

    return {"matchup": matchup, "writeup": writeup,
            "plays": plays,
            "edge_plays": [(p.player_name, p.prop_label, p.hit_rate, p.tier)
                           for p in top]}
