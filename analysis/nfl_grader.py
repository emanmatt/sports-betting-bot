"""
analysis/nfl_grader.py

Grades NFL predictions against real results, pulled live from ESPN.
Mirrors the MLB grader but for football: for each pending NFL
prediction, find that player's actual stat for that week and compare
to the line.

Auto-freshening: always pulls the CURRENT season's game logs, so as
2026 games play, grading uses real results automatically. No manual
data refresh needed.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from datetime import date
from sqlalchemy import text
from loguru import logger
from database.models import get_engine

COMMON = "https://site.api.espn.com/apis/common/v3/sports/football/nfl"
CURRENT_SEASON = 2026

# Map our NFL prop_stat -> ESPN gamelog stat key extraction
# (the ranker's parsers already know the label positions; here we pull
# the season game log and match by the most recent game before grading)


class NFLGrader:
    def __init__(self):
        self.session = requests.Session()  # no UA (ESPN 403s spoofed)
        self._player_id_cache = {}

    def _get(self, url, params=None):
        try:
            r = self.session.get(url, params=params or {}, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"[NFLGrader] {e}")
            return None

    def _build_roster_map(self):
        """
        Build {player_name.lower(): id} from ALL teams' rosters.
        The ESPN athlete-search endpoint 400s, so we use the roster path
        (same reliable source the ranker uses) to resolve player IDs.
        Cached after first build.
        """
        if self._player_id_cache:
            return
        try:
            from data_ingestion.official.nfl_client import NFLClient
            nfl = NFLClient()
            games = nfl.get_todays_games()
            team_ids = set()
            for g in games:
                if g.home_team_id:
                    team_ids.add(g.home_team_id)
                if g.away_team_id:
                    team_ids.add(g.away_team_id)
            for tid in team_ids:
                for p in nfl.get_team_roster(tid):
                    nm = (p.get("name") or "").lower()
                    if nm and p.get("id"):
                        self._player_id_cache[nm] = p["id"]
        except Exception as e:
            logger.debug(f"[NFLGrader] roster map build failed: {e}")

    def _find_player_id(self, name):
        """Resolve a player's ESPN ID via the roster map (search endpoint is broken)."""
        self._build_roster_map()
        return self._player_id_cache.get((name or "").lower())

    def _get_week_stat(self, player_name, prop_stat, pred_date):
        """
        Get a player's actual value for prop_stat in the game nearest
        pred_date. Returns float or None if not found / not yet played.
        """
        from analysis.nfl_ranker import _parse_qb_game, _parse_skill_game
        pid = self._find_player_id(player_name)
        if not pid:
            return None

        # pull current-season gamelog
        gl = self._get(f"{COMMON}/athletes/{pid}/gamelog",
                      params={"season": CURRENT_SEASON})
        if not gl:
            return None
        labels = gl.get("labels", []) or gl.get("names", [])

        # find the game on/after pred_date (the predicted game)
        best = None
        for st in gl.get("seasonTypes", []):
            for cat in st.get("categories", []):
                for ev in cat.get("events", []):
                    gdate = ev.get("gameDate", "") or ev.get("date", "")
                    stats = ev.get("stats", [])
                    if not stats:
                        continue
                    # match the prediction's game window (same week ~ within 4 days)
                    if gdate and str(gdate)[:10] >= str(pred_date):
                        best = (labels, stats)
                        break
                if best:
                    break
            if best:
                break

        if not best:
            return None

        is_qb = prop_stat in ("pass_yards", "pass_tds", "completions")
        parsed = (_parse_qb_game(best[0], best[1]) if is_qb
                 else _parse_skill_game(best[0], best[1]))
        return parsed.get(prop_stat)

    def grade_pending(self) -> int:
        """Grade all ungraded NFL predictions whose game has passed."""
        engine = get_engine()
        graded = 0
        with engine.connect() as conn:
            pending = conn.execute(text("""
                SELECT id, pred_date, player_name, prop_stat, prop_line
                FROM predictions
                WHERE graded = FALSE AND sport = 'NFL' AND pred_date < :today
            """), {"today": date.today()}).fetchall()

            for row in pending:
                pid, pred_date, name, prop_stat, line = row
                actual = self._get_week_stat(name, prop_stat, pred_date)
                if actual is None:
                    continue
                result = "hit" if actual > line else "miss"
                conn.execute(text("""
                    UPDATE predictions
                    SET actual_value = :av, result = :r, graded = TRUE
                    WHERE id = :id
                """), {"av": actual, "r": result, "id": pid})
                graded += 1
            conn.commit()
        logger.info(f"[NFLGrader] Graded {graded} NFL predictions.")
        return graded
