"""
analysis/bvp_matchup.py

Batter vs Pitcher matchup analysis:

1. PLATOON SPLITS (scoring factor — reliable):
   Batter handedness vs pitcher handedness. Lefty batters generally
   hit righty pitchers better and vice versa. This is a real, well-
   sampled effect used across baseball analytics.

2. BvP HISTORY (flag only — small sample, treated cautiously):
   How this specific batter has done vs this specific pitcher. Shown
   as a flag when the sample is meaningful (15+ AB), ignored as noise
   below that. Never a big score driver — the sample is usually too
   small to trust, which is the honest analytical consensus.

Free MLB Stats API.
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


@dataclass
class MatchupResult:
    batter_hand:   str = ""       # L / R / S (switch)
    pitcher_hand:  str = ""       # L / R
    platoon_edge:  str = "neutral"  # favorable / neutral / unfavorable
    platoon_adj:   float = 0.0    # -4 to +4 points
    # BvP history (flag)
    bvp_ab:        int = 0
    bvp_hits:      int = 0
    bvp_avg:       float = None
    bvp_flag:      str = ""       # shown only when sample >= 15 AB
    note:          str = ""


class BvPMatchup:
    """Analyzes batter-pitcher handedness and history."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._hand_cache = {}

    def _get(self, endpoint, params=None):
        try:
            r = self.session.get(f"{BASE}/{endpoint}", params=params or {}, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def _get_handedness(self, player_id: int, is_batter: bool) -> str:
        """Get a player's batting or throwing hand."""
        if not player_id:
            return ""
        if player_id in self._hand_cache:
            return self._hand_cache[player_id]

        data = self._get(f"people/{player_id}")
        hand = ""
        if data:
            people = data.get("people", [])
            if people:
                if is_batter:
                    hand = people[0].get("batSide", {}).get("code", "")
                else:
                    hand = people[0].get("pitchHand", {}).get("code", "")
        self._hand_cache[player_id] = hand
        return hand

    def _platoon_assessment(self, batter_hand: str,
                           pitcher_hand: str) -> tuple[str, float]:
        """
        Assess the platoon matchup.
        Favorable: opposite hands (L batter vs R pitcher, R vs L).
        Switch hitters (S) always get the favorable side.
        Unfavorable: same hand (L vs L, R vs R).
        """
        if not batter_hand or not pitcher_hand:
            return "neutral", 0.0

        # Switch hitters always bat from the favorable side
        if batter_hand == "S":
            return "favorable", 3.0

        # Opposite hands = favorable for the batter
        if batter_hand != pitcher_hand:
            return "favorable", 3.0
        # Same hand = unfavorable (esp. L vs L which is toughest)
        else:
            if batter_hand == "L" and pitcher_hand == "L":
                return "unfavorable", -4.0   # lefty-lefty is toughest
            return "unfavorable", -3.0

    def get_matchup(self, batter_id: int, pitcher_id: int) -> MatchupResult:
        """Full batter-pitcher matchup: platoon + BvP history."""
        result = MatchupResult()

        result.batter_hand = self._get_handedness(batter_id, is_batter=True)
        result.pitcher_hand = self._get_handedness(pitcher_id, is_batter=False)

        # Platoon
        edge, adj = self._platoon_assessment(result.batter_hand, result.pitcher_hand)
        result.platoon_edge = edge
        result.platoon_adj = adj

        hand_note = ""
        if result.batter_hand and result.pitcher_hand:
            hand_note = f"{result.batter_hand}HB vs {result.pitcher_hand}HP"
            if edge == "favorable":
                hand_note += " 🟢 platoon edge"
            elif edge == "unfavorable":
                hand_note += " 🔴 tough platoon"

        # BvP history (flag only)
        bvp = self._get_bvp_history(batter_id, pitcher_id)
        if bvp:
            result.bvp_ab = bvp.get("ab", 0)
            result.bvp_hits = bvp.get("hits", 0)
            if result.bvp_ab >= 15:  # meaningful sample threshold
                result.bvp_avg = round(result.bvp_hits / result.bvp_ab, 3)
                if result.bvp_avg >= 0.320:
                    result.bvp_flag = f"⚡ Owns him ({result.bvp_hits}/{result.bvp_ab})"
                elif result.bvp_avg <= 0.180:
                    result.bvp_flag = f"⚠️ Struggles ({result.bvp_hits}/{result.bvp_ab})"

        result.note = hand_note
        return result

    def _get_bvp_history(self, batter_id: int, pitcher_id: int) -> dict:
        """
        Get batter's career numbers vs this specific pitcher.
        Uses the vsPlayer stat split.
        """
        if not batter_id or not pitcher_id:
            return {}
        data = self._get(f"people/{batter_id}/stats", {
            "stats": "vsPlayer",
            "group": "hitting",
            "opposingPlayerId": pitcher_id,
        })
        if not data:
            return {}
        for sg in data.get("stats", []):
            for split in sg.get("splits", []):
                s = split.get("stat", {})
                return {
                    "ab": s.get("atBats", 0),
                    "hits": s.get("hits", 0),
                }
        return {}
