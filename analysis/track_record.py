"""
analysis/track_record.py

The learning loop: logs every prediction the board makes, grades them
against real game results, and computes calibration stats so the
system improves over time based on what ACTUALLY happened.

This is real "learning" — empirical calibration from outcomes, not
magic self-improvement. The system tracks how often each tier / prop
type actually hits, then that feeds back into trust.

Tables (created on first use):
  predictions — every logged pick with its context + result
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import datetime, date
from sqlalchemy import text
from loguru import logger
from database.models import get_engine, get_session

BASE = "https://statsapi.mlb.com/api/v1"


def ensure_predictions_table():
    """Create the predictions table if it doesn't exist."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS predictions (
                id SERIAL PRIMARY KEY,
                pred_date DATE,
                player_name VARCHAR(200),
                player_id VARCHAR(50),
                prop_stat VARCHAR(50),
                prop_label VARCHAR(100),
                prop_line FLOAT,
                is_pitcher BOOLEAN,
                team VARCHAR(100),
                opponent VARCHAR(100),
                game_matchup VARCHAR(200),
                tier VARCHAR(10),
                score FLOAT,
                l10_rate FLOAT,
                predicted_side VARCHAR(10),
                actual_value FLOAT,
                result VARCHAR(10),
                graded BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """))
        conn.commit()


class TrackRecord:
    """Logs predictions and grades them against results."""

    def __init__(self):
        ensure_predictions_table()
        self.db = get_session()
        import requests
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"
        })

    def close(self):
        self.db.close()

    def log_predictions(self, props: list, top_n: int = 20) -> int:
        """
        Save the top N ranked props as predictions for today.
        Avoids duplicates (same player+prop+date).
        """
        today = date.today()
        engine = get_engine()
        saved = 0

        with engine.connect() as conn:
            for p in props[:top_n]:
                # Check for existing prediction today
                existing = conn.execute(text("""
                    SELECT id FROM predictions
                    WHERE pred_date = :d AND player_name = :pn
                      AND prop_label = :pl
                """), {"d": today, "pn": p.player_name, "pl": p.prop_label}).first()
                if existing:
                    continue

                conn.execute(text("""
                    INSERT INTO predictions
                    (pred_date, player_name, prop_stat, prop_label, prop_line,
                     is_pitcher, team, opponent, game_matchup, tier, score,
                     l10_rate, predicted_side)
                    VALUES
                    (:d, :pn, :ps, :pl, :line, :isp, :team, :opp, :gm, :tier,
                     :score, :l10, :side)
                """), {
                    "d": today, "pn": p.player_name, "ps": p.prop_stat,
                    "pl": p.prop_label, "line": p.prop_line,
                    "isp": p.is_pitcher, "team": p.team, "opp": p.opponent,
                    "gm": p.game_matchup, "tier": p.tier, "score": p.score,
                    "l10": p.l10_rate, "side": "over",
                })
                saved += 1
            conn.commit()

        logger.info(f"[TrackRecord] Logged {saved} predictions for {today}.")
        return saved

    def grade_pending(self) -> int:
        """
        Grade all ungraded predictions from past dates by pulling
        actual results from MLB game logs.
        """
        engine = get_engine()
        graded = 0

        with engine.connect() as conn:
            pending = conn.execute(text("""
                SELECT id, pred_date, player_name, prop_stat, prop_line, is_pitcher
                FROM predictions
                WHERE graded = FALSE AND pred_date < :today
            """), {"today": date.today()}).fetchall()

            for row in pending:
                pred_id, pred_date, player_name, prop_stat, prop_line, is_pitcher = row
                actual = self._get_actual_result(
                    player_name, prop_stat, pred_date, is_pitcher
                )
                if actual is None:
                    continue

                result = "hit" if actual > prop_line else "miss"
                conn.execute(text("""
                    UPDATE predictions
                    SET actual_value = :av, result = :r, graded = TRUE
                    WHERE id = :id
                """), {"av": actual, "r": result, "id": pred_id})
                graded += 1
            conn.commit()

        logger.info(f"[TrackRecord] Graded {graded} predictions.")
        return graded

    def _get_actual_result(self, player_name, prop_stat, game_date, is_pitcher):
        """Pull a player's actual stat value on a given date from MLB logs."""
        from database.models import PlayerStats
        # Look in our stored game logs for that player + date
        rows = (self.db.query(PlayerStats)
               .filter(PlayerStats.sport == "MLB")
               .all())
        for s in rows:
            rs = s.raw_stats or {}
            if rs.get("player_name") != player_name:
                continue
            if str(rs.get("date", "")) != str(game_date):
                continue
            # Found the game
            if prop_stat in rs:
                return float(rs[prop_stat])
            # Derived stats
            if prop_stat == "hits_runs_rbis":
                return float(rs.get("hits", 0) + rs.get("runs", 0) + rs.get("rbi", 0))
        return None

    def get_stats(self) -> dict:
        """Compute overall + breakdown accuracy stats."""
        engine = get_engine()
        with engine.connect() as conn:
            graded = conn.execute(text("""
                SELECT tier, prop_label, is_pitcher, result, score, l10_rate
                FROM predictions WHERE graded = TRUE
            """)).fetchall()

        if not graded:
            return {"total": 0}

        total = len(graded)
        hits = sum(1 for g in graded if g[3] == "hit")

        # By tier
        by_tier = {}
        for tier in ["A", "B", "C"]:
            tier_rows = [g for g in graded if g[0] == tier]
            if tier_rows:
                tier_hits = sum(1 for g in tier_rows if g[3] == "hit")
                by_tier[tier] = {
                    "total": len(tier_rows),
                    "hits": tier_hits,
                    "rate": round(tier_hits / len(tier_rows) * 100),
                }

        # By prop type
        by_prop = {}
        prop_labels = set(g[1] for g in graded)
        for label in prop_labels:
            prop_rows = [g for g in graded if g[1] == label]
            if len(prop_rows) >= 3:  # min sample
                prop_hits = sum(1 for g in prop_rows if g[3] == "hit")
                by_prop[label] = {
                    "total": len(prop_rows),
                    "hits": prop_hits,
                    "rate": round(prop_hits / len(prop_rows) * 100),
                }

        # Batter vs pitcher
        bat_rows = [g for g in graded if not g[2]]
        pit_rows = [g for g in graded if g[2]]

        return {
            "total": total,
            "hits": hits,
            "overall_rate": round(hits / total * 100),
            "by_tier": by_tier,
            "by_prop": dict(sorted(by_prop.items(),
                                   key=lambda x: x[1]["rate"], reverse=True)),
            "batter_rate": round(sum(1 for g in bat_rows if g[3]=="hit")
                                / len(bat_rows) * 100) if bat_rows else None,
            "pitcher_rate": round(sum(1 for g in pit_rows if g[3]=="hit")
                                 / len(pit_rows) * 100) if pit_rows else None,
        }

    def get_calibration(self) -> dict:
        """
        Return score adjustments based on actual tier performance.
        If Tier A is underperforming, the model is overconfident —
        return multipliers to recalibrate.
        """
        stats = self.get_stats()
        if stats["total"] < 20:  # need enough data
            return {}

        calibration = {}
        for tier, data in stats.get("by_tier", {}).items():
            expected = {"A": 70, "B": 60, "C": 50}.get(tier, 55)
            actual = data["rate"]
            # If actual is much lower than expected, flag it
            calibration[tier] = {
                "expected": expected,
                "actual": actual,
                "diff": actual - expected,
                "sample": data["total"],
            }
        return calibration

    def get_recent_results(self, limit: int = 30) -> list[dict]:
        """Get recent graded predictions for display."""
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT pred_date, player_name, prop_label, tier, score,
                       actual_value, result
                FROM predictions WHERE graded = TRUE
                ORDER BY pred_date DESC, score DESC
                LIMIT :lim
            """), {"lim": limit}).fetchall()

        return [{
            "date": str(r[0]), "player": r[1], "prop": r[2], "tier": r[3],
            "score": r[4], "actual": r[5], "result": r[6],
        } for r in rows]
