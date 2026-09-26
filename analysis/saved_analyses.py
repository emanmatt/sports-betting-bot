"""
analysis/saved_analyses.py

Durable storage for saved game analyses AND TD boards, so your best work
survives app reboots. Backed by the same Postgres (Supabase) engine as the
rest of the app. Table + columns are created/upgraded lazily on first use —
no manual migration needed.

Each row has a `kind`: 'analysis' or 'td'. Ratings (0-5) drive the
leaderboards in the Game Analysis tab.
"""

import json
from loguru import logger
from sqlalchemy import text


def _engine():
    from database.models import get_engine
    return get_engine()


_DDL = """
CREATE TABLE IF NOT EXISTS saved_analyses (
    id SERIAL PRIMARY KEY,
    matchup TEXT NOT NULL,
    sport TEXT DEFAULT 'NFL',
    writeup TEXT,
    edge_plays TEXT,
    rating INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
)
"""


def ensure_table():
    eng = _engine()
    with eng.begin() as c:
        c.execute(text(_DDL))
        # add the kind column on existing installs (safe if it already exists)
        c.execute(text("ALTER TABLE saved_analyses "
                       "ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'analysis'"))


def save_analysis(matchup, sport, writeup, edge_plays, kind="analysis"):
    """Insert or refresh a saved item. Re-saving the same matchup+kind updates
    the text but keeps whatever rating you already gave it."""
    ensure_table()
    eng = _engine()
    plays_json = json.dumps(edge_plays or [])
    with eng.begin() as c:
        row = c.execute(
            text("SELECT id FROM saved_analyses "
                 "WHERE matchup=:m AND sport=:s AND kind=:k"),
            {"m": matchup, "s": sport, "k": kind}).fetchone()
        if row:
            c.execute(text(
                "UPDATE saved_analyses SET writeup=:w, edge_plays=:e, "
                "created_at=NOW() WHERE id=:i"),
                {"w": writeup, "e": plays_json, "i": row[0]})
            return row[0]
        res = c.execute(text(
            "INSERT INTO saved_analyses (matchup, sport, writeup, edge_plays, kind) "
            "VALUES (:m, :s, :w, :e, :k) RETURNING id"),
            {"m": matchup, "s": sport, "w": writeup, "e": plays_json, "k": kind})
        return res.fetchone()[0]


def list_saved(sport=None, kind=None):
    """Saved items, best-rated first. Filter by sport and/or kind."""
    ensure_table()
    eng = _engine()
    q = ("SELECT id, matchup, sport, writeup, edge_plays, rating, created_at, kind "
         "FROM saved_analyses")
    clauses, params = [], {}
    if sport:
        clauses.append("sport=:s"); params["s"] = sport
    if kind:
        clauses.append("kind=:k"); params["k"] = kind
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY rating DESC, created_at DESC"
    with eng.connect() as c:
        rows = c.execute(text(q), params).fetchall()
    out = []
    for r in rows:
        try:
            plays = json.loads(r[4]) if r[4] else []
        except Exception:
            plays = []
        out.append({"id": r[0], "matchup": r[1], "sport": r[2],
                    "writeup": r[3], "edge_plays": plays,
                    "rating": r[5] or 0, "created_at": r[6],
                    "kind": r[7] or "analysis"})
    return out


def set_rating(analysis_id, rating):
    ensure_table()
    eng = _engine()
    with eng.begin() as c:
        c.execute(text("UPDATE saved_analyses SET rating=:r WHERE id=:i"),
                  {"r": int(rating), "i": int(analysis_id)})


def delete_saved(analysis_id):
    ensure_table()
    eng = _engine()
    with eng.begin() as c:
        c.execute(text("DELETE FROM saved_analyses WHERE id=:i"),
                  {"i": int(analysis_id)})
