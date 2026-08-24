"""
analysis/team_quality.py

Pulls team-level offensive and defensive/pitching quality from the
MLB Stats API to adjust props based on the OPPONENT, not just the
player's own form.

For PITCHER props (outs, strikeouts, hits allowed):
  - Facing a strong offense (high OBP, low K%) = harder = lower score
  - Facing a weak offense (low OBP, high K%) = easier = higher score

For BATTER props (hits, total bases):
  - Facing a strong pitching staff (low team ERA) = harder
  - Facing a weak staff/bullpen = easier

Free MLB Stats API, cached per session.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from dataclasses import dataclass
from loguru import logger

BASE = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"}
SEASON = 2026

# Team name -> MLB team ID (for stats lookup)
TEAM_IDS = {
    "Arizona Diamondbacks": 109, "Atlanta Braves": 144, "Baltimore Orioles": 110,
    "Boston Red Sox": 111, "Chicago Cubs": 112, "Chicago White Sox": 145,
    "Cincinnati Reds": 113, "Cleveland Guardians": 114, "Colorado Rockies": 115,
    "Detroit Tigers": 116, "Houston Astros": 117, "Kansas City Royals": 118,
    "Los Angeles Angels": 108, "Los Angeles Dodgers": 119, "Miami Marlins": 146,
    "Milwaukee Brewers": 158, "Minnesota Twins": 142, "New York Mets": 121,
    "New York Yankees": 147, "Athletics": 133, "Oakland Athletics": 133,
    "Philadelphia Phillies": 143, "Pittsburgh Pirates": 134, "San Diego Padres": 135,
    "San Francisco Giants": 137, "Seattle Mariners": 136, "St. Louis Cardinals": 138,
    "Tampa Bay Rays": 139, "Texas Rangers": 140, "Toronto Blue Jays": 141,
    "Washington Nationals": 120,
}


@dataclass
class TeamQuality:
    team:          str
    # Offense
    runs_per_game: float = None
    team_obp:      float = None
    team_k_rate:   float = None    # strikeout rate (higher = easier for pitchers)
    offense_grade: str = "average"  # strong / average / weak
    # Pitching/defense
    team_era:      float = None
    pitching_grade: str = "average"


class TeamQualityEngine:
    """Pulls and grades team offensive/pitching quality."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._cache = {}
        self._league_avg = None

    def _get(self, endpoint, params=None):
        try:
            r = self.session.get(f"{BASE}/{endpoint}", params=params or {}, timeout=12)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"[TeamQuality] {e}")
            return None

    def get_team_quality(self, team_name: str) -> TeamQuality:
        """Get a team's offensive + pitching quality, graded."""
        if team_name in self._cache:
            return self._cache[team_name]

        tq = TeamQuality(team=team_name)
        team_id = TEAM_IDS.get(team_name)
        if not team_id:
            return tq

        # Offensive stats
        hitting = self._get(f"teams/{team_id}/stats", {
            "stats": "season", "group": "hitting", "season": SEASON,
        })
        if hitting:
            for sg in hitting.get("stats", []):
                for split in sg.get("splits", []):
                    s = split.get("stat", {})
                    gp = s.get("gamesPlayed", 1) or 1
                    runs = s.get("runs", 0) or 0
                    tq.runs_per_game = round(runs / gp, 2) if gp else None
                    tq.team_obp = float(s.get("obp", 0) or 0)
                    ab = s.get("atBats", 0) or 0
                    so = s.get("strikeOuts", 0) or 0
                    pa = s.get("plateAppearances", ab) or ab or 1
                    tq.team_k_rate = round(so / pa, 3) if pa else None

        # Pitching stats
        pitching = self._get(f"teams/{team_id}/stats", {
            "stats": "season", "group": "pitching", "season": SEASON,
        })
        if pitching:
            for sg in pitching.get("stats", []):
                for split in sg.get("splits", []):
                    s = split.get("stat", {})
                    tq.team_era = float(s.get("era", 0) or 0)

        tq = self._grade(tq)
        self._cache[team_name] = tq
        return tq

    def _grade(self, tq: TeamQuality) -> TeamQuality:
        """Grade offense and pitching relative to typical MLB averages."""
        # Offense grade (league avg ~4.4 R/G, ~.315 OBP, ~22% K rate)
        if tq.runs_per_game is not None and tq.team_obp is not None:
            off_score = 0
            if tq.runs_per_game >= 4.9:
                off_score += 2
            elif tq.runs_per_game >= 4.5:
                off_score += 1
            elif tq.runs_per_game <= 3.9:
                off_score -= 2
            elif tq.runs_per_game <= 4.2:
                off_score -= 1

            if tq.team_obp >= 0.335:
                off_score += 2
            elif tq.team_obp >= 0.320:
                off_score += 1
            elif tq.team_obp <= 0.300:
                off_score -= 2

            if off_score >= 2:
                tq.offense_grade = "strong"
            elif off_score <= -2:
                tq.offense_grade = "weak"
            else:
                tq.offense_grade = "average"

        # Pitching grade (league avg ERA ~4.1)
        if tq.team_era is not None:
            if tq.team_era <= 3.60:
                tq.pitching_grade = "strong"
            elif tq.team_era >= 4.60:
                tq.pitching_grade = "weak"
            else:
                tq.pitching_grade = "average"

        return tq

    # ── Adjustments ────────────────────────────────────────────────────

    def pitcher_prop_adjustment(self, opposing_offense: TeamQuality) -> tuple[float, str]:
        """
        Adjustment for a PITCHER prop based on the offense they face.
        Strong offense = harder to go deep / rack up outs = negative.
        Also considers K rate: high-K offense = easier strikeouts.
        Returns (adjustment_points, note).
        """
        if opposing_offense.offense_grade == "strong":
            return -8, f"🔴 vs strong offense ({opposing_offense.team} " \
                       f"{opposing_offense.runs_per_game} R/G)"
        elif opposing_offense.offense_grade == "weak":
            return 6, f"🟢 vs weak offense ({opposing_offense.team} " \
                      f"{opposing_offense.runs_per_game} R/G)"
        return 0, f"➖ vs average offense ({opposing_offense.team})"

    def batter_prop_adjustment(self, opposing_pitching: TeamQuality) -> tuple[float, str]:
        """
        Adjustment for a BATTER prop based on the opposing team's pitching
        staff quality (affects bullpen innings especially).
        Strong staff = harder to hit = negative.
        Returns (adjustment_points, note).
        """
        if opposing_pitching.pitching_grade == "strong":
            return -5, f"🔴 vs strong staff (ERA {opposing_pitching.team_era})"
        elif opposing_pitching.pitching_grade == "weak":
            return 5, f"🟢 vs weak staff (ERA {opposing_pitching.team_era})"
        return 0, "➖ vs average staff"
