"""
analysis/dvp_engine.py

Defense-vs-Position (DvP): how many rushing/receiving yards, receptions and TDs
each NFL defense allows to RBs, WRs and TEs — ranked 1-32 across the league.

ESPN doesn't expose DvP directly, so we COMPUTE it: every skill player's per-game
yards are attributed to the defense they faced (the game log carries the
opponent) and their position. Aggregated league-wide, divided by games played,
and ranked. Rank 1 = MOST allowed = softest matchup.

This is heavy (~300 game-log reads) so it's computed once and cached in the DB
(kv_cache table). The analysis reads the cache instantly; refresh weekly.
All ESPN — no OddsAPI credits.
"""

import sys
import json
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from sqlalchemy import text

TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
SKILL = {"RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE"}
CACHE_KEY = "dvp_nfl"


def _num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _engine():
    from database.models import get_engine
    return get_engine()


# ---------- cache ----------
def _ensure_cache():
    eng = _engine()
    with eng.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS kv_cache ("
                       "key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP)"))


def save_dvp(blob):
    _ensure_cache()
    eng = _engine()
    payload = json.dumps(blob)
    with eng.begin() as c:
        row = c.execute(text("SELECT key FROM kv_cache WHERE key=:k"),
                        {"k": CACHE_KEY}).fetchone()
        if row:
            c.execute(text("UPDATE kv_cache SET value=:v, updated_at=:t WHERE key=:k"),
                      {"v": payload, "t": datetime.utcnow(), "k": CACHE_KEY})
        else:
            c.execute(text("INSERT INTO kv_cache (key, value, updated_at) "
                           "VALUES (:k, :v, :t)"),
                      {"k": CACHE_KEY, "v": payload, "t": datetime.utcnow()})


def load_dvp():
    try:
        _ensure_cache()
        eng = _engine()
        with eng.connect() as c:
            row = c.execute(text("SELECT value FROM kv_cache WHERE key=:k"),
                            {"k": CACHE_KEY}).fetchone()
        return json.loads(row[0]) if row else {}
    except Exception as e:
        logger.debug(f"[DvP] load failed: {e}")
        return {}


# ---------- compute ----------
def _fetch_teams():
    data = json.load(urllib.request.urlopen(TEAMS_URL, timeout=25))
    out = []
    for lg in data.get("sports", [{}])[0].get("leagues", [{}]):
        for t in lg.get("teams", []):
            tm = t.get("team", {})
            out.append({"id": tm.get("id"), "abbr": tm.get("abbreviation"),
                        "name": tm.get("displayName")})
    return out


def compute_dvp(nfl):
    """nfl = ranker.nfl (has get_team_roster). Returns the full DvP blob."""
    teams = _fetch_teams()
    name_to_abbr = {t["name"]: t["abbr"] for t in teams if t["abbr"]}

    # collect skill players league-wide
    players = []
    for t in teams:
        try:
            for pl in nfl.get_team_roster(t["id"]):
                pos = (pl.get("position") if isinstance(pl, dict)
                       else getattr(pl, "position", "")) or ""
                grp = SKILL.get(pos.upper())
                if grp:
                    pid = pl.get("id") if isinstance(pl, dict) else getattr(pl, "id", None)
                    if pid:
                        players.append((str(pid), grp))
        except Exception:
            continue

    from analysis.td_data import _fetch_gamelog

    # agg[defense][posgroup] = totals ; games[defense] = set(eventIds)
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    games = defaultdict(set)

    def work(pp):
        pid, grp = pp
        try:
            gl = _fetch_gamelog(pid)
        except Exception:
            return None
        names = gl.get("names") or []
        meta = gl.get("events") or {}
        rows = []
        for season in gl.get("seasonTypes") or []:
            if "regular season" not in (season.get("displayName") or "").lower():
                continue
            for cat in season.get("categories", []):
                for ev in cat.get("events", []):
                    eid = ev.get("eventId")
                    stats = ev.get("stats")
                    if not eid or not stats or len(stats) != len(names):
                        continue
                    opp = (meta.get(eid, {}).get("opponent", {}) or {}).get("abbreviation")
                    if not opp:
                        continue
                    r = dict(zip(names, stats))
                    rows.append((opp, eid, r))
        return (grp, rows)

    with ThreadPoolExecutor(max_workers=10) as ex:
        for res in ex.map(work, players):
            if not res:
                continue
            grp, rows = res
            for opp, eid, r in rows:
                games[opp].add(eid)
                a = agg[opp][grp]
                a["rush_yds"] += _num(r.get("rushingYards"))
                a["rec_yds"] += _num(r.get("receivingYards"))
                a["rec"] += _num(r.get("receptions"))
                a["rush_td"] += _num(r.get("rushingTouchdowns"))
                a["rec_td"] += _num(r.get("receivingTouchdowns"))

    # per-game
    dvp = {}
    for d, groups in agg.items():
        g = max(1, len(games[d]))
        dvp[d] = {"games": len(games[d])}
        for grp, tot in groups.items():
            dvp[d][grp] = {k: round(v / g, 1) for k, v in tot.items()}

    # ranks: rank 1 = MOST allowed (softest). Per (group, metric).
    metrics = {"RB": ["rush_yds", "rec_yds", "rec", "rush_td"],
               "WR": ["rec_yds", "rec", "rec_td"],
               "TE": ["rec_yds", "rec", "rec_td"]}
    ranks = defaultdict(dict)
    for grp, mets in metrics.items():
        for m in mets:
            vals = [(d, dvp[d].get(grp, {}).get(m, 0.0)) for d in dvp]
            vals.sort(key=lambda x: x[1], reverse=True)
            for i, (d, _) in enumerate(vals, 1):
                ranks[d].setdefault(grp, {})[m] = i

    return {"dvp": dvp, "ranks": ranks, "name_to_abbr": name_to_abbr,
            "n_teams": len(dvp), "updated": datetime.utcnow().isoformat()}


def refresh_dvp(nfl):
    blob = compute_dvp(nfl)
    save_dvp(blob)
    return blob


# ---------- read for the analysis ----------
_LABEL = {"rush_yds": "rush yds", "rec_yds": "rec yds", "rec": "rec",
          "rush_td": "rush TD", "rec_td": "rec TD"}


def dvp_summary(blob, team_full_name):
    """Human line of how `team_full_name`'s DEFENSE ranks vs positions.
    Rank shown as N/32 where 1 = softest (most allowed)."""
    if not blob:
        return ""
    abbr = blob.get("name_to_abbr", {}).get(team_full_name)
    if not abbr:
        # nickname fallback
        nick = team_full_name.split()[-1]
        for nm, ab in blob.get("name_to_abbr", {}).items():
            if nm.split()[-1] == nick:
                abbr = ab
                break
    if not abbr:
        return ""
    d = blob.get("dvp", {}).get(abbr)
    rk = blob.get("ranks", {}).get(abbr, {})
    n = blob.get("n_teams", 32)
    if not d:
        return ""
    parts = []
    for grp in ("RB", "WR", "TE"):
        g = d.get(grp)
        if not g:
            continue
        bits = []
        for m in ("rush_yds", "rec_yds", "rec"):
            if m in g:
                r = rk.get(grp, {}).get(m)
                rtxt = f" ({r}/{n})" if r else ""
                bits.append(f"{g[m]:g} {_LABEL[m]}{rtxt}")
        if bits:
            parts.append(f"vs {grp}: " + ", ".join(bits))
    if not parts:
        return ""
    gm = d.get("games", "?")
    return f"{abbr} D allows (per game, {gm} gm) — " + " | ".join(parts)
