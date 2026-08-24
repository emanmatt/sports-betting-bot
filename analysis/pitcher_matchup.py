"""
analysis/pitcher_matchup.py

Assesses the opposing pitcher's quality to adjust batter hit props.
A batter's L10 hit rate was built against a mix of pitchers — facing
an ace tonight should lower the expectation; facing a weak arm raises it.

Pulls the pitcher's season stats from MLB Stats API (free) and
computes a difficulty adjustment.
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
class PitcherQuality:
    name:        str
    era:         float = None
    whip:        float = None
    k_per_9:     float = None
    difficulty:  str = "average"   # tough / average / soft
    adjustment:  float = 0.0       # -12 to +8 points for batter props
    note:        str = ""


class PitcherMatchup:
    """Analyzes opposing pitcher quality for batter prop adjustment."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._cache = {}

    def get_pitcher_quality(self, pitcher_name: str,
                            pitcher_id: int = None) -> PitcherQuality:
        """
        Get a pitcher's quality rating. Needs pitcher_id for stats;
        if only name given, returns neutral (can't look up without ID).
        """
        if not pitcher_id and not pitcher_name:
            return PitcherQuality(name="TBD")

        cache_key = pitcher_id or pitcher_name
        if cache_key in self._cache:
            return self._cache[cache_key]

        pq = PitcherQuality(name=pitcher_name)

        if not pitcher_id:
            # Try to find pitcher by name
            try:
                search = self.session.get(
                    f"{BASE}/people/search",
                    params={"names": pitcher_name}, timeout=10
                )
                if search.ok:
                    people = search.json().get("people", [])
                    if people:
                        pitcher_id = people[0].get("id")
            except Exception:
                pass

        if not pitcher_id:
            return pq

        # Fetch season pitching stats
        try:
            resp = self.session.get(
                f"{BASE}/people/{pitcher_id}",
                params={"hydrate": f"stats(group=[pitching],type=[season],season={SEASON})"},
                timeout=12
            )
            resp.raise_for_status()
            people = resp.json().get("people", [])
            if people:
                for sg in people[0].get("stats", []):
                    for split in sg.get("splits", []):
                        s = split.get("stat", {})
                        pq.era = float(s.get("era", 0) or 0)
                        pq.whip = float(s.get("whip", 0) or 0)
                        k9 = s.get("strikeoutsPer9Inn")
                        pq.k_per_9 = float(k9) if k9 else None
        except Exception as e:
            logger.debug(f"[PitcherMatchup] Failed for {pitcher_name}: {e}")
            return pq

        # Grade difficulty
        pq = self._grade(pq)
        self._cache[cache_key] = pq
        return pq

    def _grade(self, pq: PitcherQuality) -> PitcherQuality:
        """
        Grade pitcher difficulty for batters.
        Lower ERA/WHIP + higher K/9 = tougher = worse for batter hit props.
        """
        if pq.era is None or pq.whip is None:
            pq.difficulty = "average"
            pq.adjustment = 0.0
            return pq

        score = 0  # negative = tough pitcher (bad for batters)

        # ERA
        if pq.era <= 3.00:
            score -= 5
        elif pq.era <= 3.75:
            score -= 2
        elif pq.era >= 5.00:
            score += 4
        elif pq.era >= 4.50:
            score += 2

        # WHIP (baserunners allowed — higher = more hits allowed = good for batters)
        if pq.whip <= 1.05:
            score -= 5
        elif pq.whip <= 1.20:
            score -= 2
        elif pq.whip >= 1.45:
            score += 4
        elif pq.whip >= 1.35:
            score += 2

        # K/9 (strikeout pitchers suppress contact = fewer hits)
        if pq.k_per_9 is not None:
            if pq.k_per_9 >= 10.5:
                score -= 3
            elif pq.k_per_9 >= 9.0:
                score -= 1
            elif pq.k_per_9 <= 6.5:
                score += 2

        pq.adjustment = max(-12, min(8, score))

        if pq.adjustment <= -5:
            pq.difficulty = "tough"
            pq.note = f"🔴 Tough matchup (ERA {pq.era}, WHIP {pq.whip})"
        elif pq.adjustment >= 4:
            pq.difficulty = "soft"
            pq.note = f"🟢 Favorable matchup (ERA {pq.era}, WHIP {pq.whip})"
        else:
            pq.difficulty = "average"
            pq.note = f"➖ Average matchup (ERA {pq.era}, WHIP {pq.whip})"

        return pq
