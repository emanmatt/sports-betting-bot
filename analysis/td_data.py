"""
analysis/td_data.py

Real touchdown data from ESPN game logs — no guessing. For each skill player
we pull their game log and compute:
  - anytime-TD rate (rush + rec TDs per game)
  - a data-based anytime-TD probability = 1 - exp(-rate)  (Poisson on their
    actual scoring rate; a genuine baseline, not a vibe)
  - volume: rush attempts/game and targets/game (the goal-line / RZ proxy)

ESPN's free feed (send NO custom headers). Fetches run in parallel so a full
game is a few seconds.
"""

import json
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

_GAMELOG = ("https://site.web.api.espn.com/apis/common/v3/sports/football/"
            "nfl/athletes/{aid}/gamelog")

SKILL_POS = {"QB", "RB", "WR", "TE", "FB"}


def _num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _fetch_gamelog(aid):
    with urllib.request.urlopen(_GAMELOG.format(aid=aid), timeout=25) as r:
        return json.load(r)


def player_td_profile(aid):
    """Real TD/volume profile for one player id, or None if unavailable."""
    try:
        gl = _fetch_gamelog(aid)
    except Exception as e:
        logger.debug(f"[TDData] gamelog {aid} failed: {e}")
        return None
    names = gl.get("names") or []
    if not names:
        return None

    # Collect regular-season events (names line up with each event's stats)
    events = []
    for season in gl.get("seasonTypes") or []:
        disp = (season.get("displayName") or "").lower()
        if "regular season" not in disp:
            continue
        for cat in season.get("categories", []):
            for ev in cat.get("events", []):
                stats = ev.get("stats")
                if stats and len(stats) == len(names):
                    events.append(dict(zip(names, stats)))
    if not events:  # fallback: take anything with aligned stats
        for season in gl.get("seasonTypes") or []:
            for cat in season.get("categories", []):
                for ev in cat.get("events", []):
                    stats = ev.get("stats")
                    if stats and len(stats) == len(names):
                        events.append(dict(zip(names, stats)))
    if not events:
        return None

    g = len(events)
    rush_td = sum(_num(e.get("rushingTouchdowns")) for e in events)
    rec_td = sum(_num(e.get("receivingTouchdowns")) for e in events)
    pass_td = sum(_num(e.get("passingTouchdowns")) for e in events)
    rush_att = sum(_num(e.get("rushingAttempts")) for e in events)
    tgts = sum(_num(e.get("receivingTargets")) for e in events)

    anytime = rush_td + rec_td
    rate = anytime / g if g else 0.0
    p_anytime = 1.0 - math.exp(-rate)  # P(>=1 TD) under Poisson(rate)

    return {
        "games": g,
        "anytime_tds": anytime,
        "td_rate": rate,
        "p_anytime": p_anytime,
        "rush_att_pg": rush_att / g if g else 0.0,
        "tgts_pg": tgts / g if g else 0.0,
        "rush_tds": rush_td,
        "rec_tds": rec_td,
        "pass_tds": pass_td,
    }


def game_td_data(game, ranker):
    """Real TD profiles for every skill player in a game, best P(anytime) first."""
    players = []
    for team_id, team in [(game.away_team_id, game.away_team),
                          (game.home_team_id, game.home_team)]:
        try:
            for pl in ranker.nfl.get_team_roster(team_id):
                pos = (pl.get("position") if isinstance(pl, dict)
                       else getattr(pl, "position", "")) or ""
                if pos.upper() in SKILL_POS:
                    pid = pl.get("id") if isinstance(pl, dict) else getattr(pl, "id", None)
                    name = pl.get("name") if isinstance(pl, dict) else getattr(pl, "name", "")
                    if pid:
                        players.append((str(pid), name, pos.upper(), team))
        except Exception:
            continue

    def work(p):
        aid, name, pos, team = p
        prof = player_td_profile(aid)
        if not prof or prof["games"] == 0:
            return None
        prof.update({"player": name, "pos": pos, "team": team})
        return prof

    rows = []
    if players:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for r in ex.map(work, players):
                if r:
                    rows.append(r)
    rows.sort(key=lambda x: (x["p_anytime"], x["td_rate"]), reverse=True)
    return rows


def data_table_md(rows, top=10):
    """Compact markdown table of the real TD data for the board / display."""
    if not rows:
        return "_(no TD data available)_"
    lines = ["| Player | Pos | Team | TD/gm | P(any) | Rush/gm | Tgts/gm | Sample |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows[:top]:
        lines.append(
            f"| {r['player']} | {r['pos']} | {r['team']} | "
            f"{r['td_rate']:.2f} | {r['p_anytime']*100:.0f}% | "
            f"{r['rush_att_pg']:.1f} | {r['tgts_pg']:.1f} | {r['games']} gm |")
    return "\n".join(lines)
