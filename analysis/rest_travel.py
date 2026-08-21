"""
analysis/rest_travel.py

Computes rest and travel fatigue factors from the schedule:
  - Days of rest since last game
  - Travel distance between series
  - Time zones crossed (jet lag)
  - Day game after night game
  - Long road trips

These are Tier 2 contextual factors that affect performance,
especially for bats (fatigue lowers contact) and bullpens.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from loguru import logger

# Approximate city coordinates for travel distance (team home cities)
TEAM_COORDS = {
    "Boston Red Sox":       (42.35, -71.06),
    "New York Yankees":     (40.83, -73.93),
    "Tampa Bay Rays":       (27.77, -82.65),
    "Toronto Blue Jays":    (43.64, -79.39),
    "Baltimore Orioles":    (39.28, -76.62),
    "Cleveland Guardians":  (41.50, -81.69),
    "Detroit Tigers":       (42.34, -83.05),
    "Chicago White Sox":    (41.83, -87.63),
    "Kansas City Royals":   (39.05, -94.48),
    "Minnesota Twins":      (44.98, -93.28),
    "Houston Astros":       (29.76, -95.36),
    "Seattle Mariners":     (47.59, -122.33),
    "Los Angeles Angels":   (33.80, -117.88),
    "Texas Rangers":        (32.75, -97.08),
    "Oakland Athletics":    (37.75, -122.20),
    "Atlanta Braves":       (33.89, -84.47),
    "Philadelphia Phillies": (39.91, -75.17),
    "New York Mets":        (40.76, -73.85),
    "Miami Marlins":        (25.78, -80.22),
    "Washington Nationals": (38.87, -77.01),
    "Milwaukee Brewers":    (43.03, -87.97),
    "Chicago Cubs":         (41.95, -87.66),
    "Cincinnati Reds":      (39.10, -84.51),
    "Pittsburgh Pirates":   (40.45, -80.01),
    "St. Louis Cardinals":  (38.62, -90.19),
    "Los Angeles Dodgers":  (34.07, -118.24),
    "San Francisco Giants": (37.78, -122.39),
    "San Diego Padres":     (32.71, -117.16),
    "Arizona Diamondbacks": (33.45, -112.07),
    "Colorado Rockies":     (39.76, -104.99),
}

# Rough timezone by longitude
def _timezone_offset(lon: float) -> int:
    return round(lon / 15)


@dataclass
class RestTravelReport:
    team:            str
    days_rest:       int = None
    traveled_miles:  float = None
    timezones_crossed: int = 0
    day_after_night: bool = False
    long_road_trip:  bool = False
    fatigue_score:   float = 0.0    # 0 (fresh) to 10 (exhausted)
    summary:         str = ""


class RestTravelEngine:
    """Computes rest/travel fatigue from schedule data."""

    def _haversine(self, c1: tuple, c2: tuple) -> float:
        """Distance in miles between two lat/lon points."""
        lat1, lon1 = c1
        lat2, lon2 = c2
        R = 3959  # Earth radius miles
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat/2)**2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon/2)**2)
        return R * 2 * math.asin(math.sqrt(a))

    def assess(self, team: str, current_city: str,
               previous_city: str = None,
               days_rest: int = None,
               day_after_night: bool = False) -> RestTravelReport:
        """
        Assess fatigue for a team.
        current_city / previous_city: team names (home cities used)
        """
        report = RestTravelReport(team=team, days_rest=days_rest,
                                 day_after_night=day_after_night)

        fatigue = 0.0

        # Travel distance + timezones
        if previous_city and previous_city in TEAM_COORDS and \
           current_city in TEAM_COORDS:
            prev = TEAM_COORDS[previous_city]
            curr = TEAM_COORDS[current_city]
            miles = self._haversine(prev, curr)
            report.traveled_miles = round(miles)

            tz_prev = _timezone_offset(prev[1])
            tz_curr = _timezone_offset(curr[1])
            report.timezones_crossed = abs(tz_curr - tz_prev)

            # Fatigue from travel
            if miles > 2000:
                fatigue += 3
            elif miles > 1000:
                fatigue += 2
            elif miles > 500:
                fatigue += 1

            # Jet lag (crossing timezones, worse going east)
            fatigue += report.timezones_crossed * 0.8

        # Days rest
        if days_rest is not None:
            if days_rest == 0:
                fatigue += 2      # No rest
            elif days_rest >= 2:
                fatigue -= 1      # Well rested

        # Day after night game
        if day_after_night:
            fatigue += 1.5

        report.fatigue_score = max(0, min(10, round(fatigue, 1)))

        # Summary
        parts = []
        if report.traveled_miles:
            parts.append(f"traveled {report.traveled_miles} mi")
        if report.timezones_crossed:
            parts.append(f"{report.timezones_crossed} TZ crossed")
        if report.day_after_night:
            parts.append("day-after-night")
        if days_rest == 0:
            parts.append("no rest day")

        if report.fatigue_score >= 5:
            level = "HIGH fatigue"
        elif report.fatigue_score >= 3:
            level = "MODERATE fatigue"
        else:
            level = "fresh"

        report.summary = f"{level}" + (f" ({', '.join(parts)})" if parts else "")
        return report

    def format_for_analysis(self, report: RestTravelReport) -> str:
        return f"{report.team}: {report.summary} [fatigue {report.fatigue_score}/10]"
