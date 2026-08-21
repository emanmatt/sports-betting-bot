"""
data_ingestion/official/weather_engine.py

Pulls weather + wind conditions at MLB stadiums and assesses
their impact on scoring, totals, and home run props.

Wind is one of the biggest hidden factors in baseball:
  - Wind blowing OUT boosts home runs and scoring
  - Wind blowing IN suppresses them
  - Crosswinds affect fly balls unpredictably

Uses free Open-Meteo API (no key needed).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from dataclasses import dataclass
from loguru import logger

# Open-Meteo — free, no API key
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# MLB stadium coordinates + orientation (home plate to center field bearing)
# Orientation matters: wind "out to CF" depends on stadium direction
STADIUMS = {
    "Fenway Park":            {"lat": 42.3467, "lon": -71.0972, "cf_bearing": 40,  "dome": False},
    "Yankee Stadium":         {"lat": 40.8296, "lon": -73.9262, "cf_bearing": 30,  "dome": False},
    "Wrigley Field":          {"lat": 41.9484, "lon": -87.6553, "cf_bearing": 30,  "dome": False},
    "Dodger Stadium":         {"lat": 34.0739, "lon": -118.2400, "cf_bearing": 25, "dome": False},
    "Oracle Park":            {"lat": 37.7786, "lon": -122.3893, "cf_bearing": 90, "dome": False},
    "Coors Field":            {"lat": 39.7559, "lon": -104.9942, "cf_bearing": 0,  "dome": False},
    "Great American Ball Park": {"lat": 39.0975, "lon": -84.5069, "cf_bearing": 40, "dome": False},
    "Citizens Bank Park":     {"lat": 39.9061, "lon": -75.1665, "cf_bearing": 10,  "dome": False},
    "Truist Park":            {"lat": 33.8908, "lon": -84.4678, "cf_bearing": 25,  "dome": False},
    "loanDepot park":         {"lat": 25.7781, "lon": -80.2197, "cf_bearing": 30,  "dome": True},
    "Target Field":           {"lat": 44.9817, "lon": -93.2776, "cf_bearing": 15,  "dome": False},
    "Progressive Field":      {"lat": 41.4962, "lon": -81.6852, "cf_bearing": 0,   "dome": False},
    "Comerica Park":          {"lat": 42.3390, "lon": -83.0485, "cf_bearing": 30,  "dome": False},
    "Kauffman Stadium":       {"lat": 39.0517, "lon": -94.4803, "cf_bearing": 0,   "dome": False},
    "Guaranteed Rate Field":  {"lat": 41.8299, "lon": -87.6338, "cf_bearing": 5,   "dome": False},
    "Minute Maid Park":       {"lat": 29.7572, "lon": -95.3555, "cf_bearing": 20,  "dome": True},
    "Globe Life Field":       {"lat": 32.7473, "lon": -97.0847, "cf_bearing": 0,   "dome": True},
    "T-Mobile Park":          {"lat": 47.5914, "lon": -122.3325, "cf_bearing": 0,  "dome": True},
    "Oakland Coliseum":       {"lat": 37.7516, "lon": -122.2005, "cf_bearing": 60, "dome": False},
    "Angel Stadium":          {"lat": 33.8003, "lon": -117.8827, "cf_bearing": 45, "dome": False},
    "Petco Park":             {"lat": 32.7073, "lon": -117.1566, "cf_bearing": 0,  "dome": False},
    "Chase Field":            {"lat": 33.4455, "lon": -112.0667, "cf_bearing": 0,  "dome": True},
    "Nationals Park":         {"lat": 38.8730, "lon": -77.0074, "cf_bearing": 30,  "dome": False},
    "Citi Field":             {"lat": 40.7571, "lon": -73.8458, "cf_bearing": 25,  "dome": False},
    "PNC Park":               {"lat": 40.4469, "lon": -80.0057, "cf_bearing": 60,  "dome": False},
    "Busch Stadium":          {"lat": 38.6226, "lon": -90.1928, "cf_bearing": 20,  "dome": False},
    "American Family Field":  {"lat": 43.0280, "lon": -87.9712, "cf_bearing": 0,   "dome": True},
    "Rogers Centre":          {"lat": 43.6414, "lon": -79.3894, "cf_bearing": 0,   "dome": True},
    "Camden Yards":           {"lat": 39.2839, "lon": -76.6217, "cf_bearing": 20,  "dome": False},
    "Tropicana Field":        {"lat": 27.7683, "lon": -82.6534, "cf_bearing": 0,   "dome": True},
}


@dataclass
class WeatherReport:
    stadium:        str
    is_dome:        bool = False
    temp_f:         float = None
    wind_speed_mph: float = None
    wind_dir_deg:   float = None    # meteorological (from direction)
    wind_effect:    str = ""        # "out" / "in" / "crosswind" / "dome"
    humidity:       float = None
    precipitation:  float = None
    impact_summary: str = ""
    total_lean:     str = ""        # "over" / "under" / "neutral"


class WeatherEngine:
    """Pulls stadium weather and assesses baseball impact."""

    def __init__(self):
        self.session = requests.Session()

    def get_stadium_weather(self, stadium_name: str) -> WeatherReport:
        """Get current/forecast weather for a stadium."""
        # Match stadium (fuzzy)
        stadium_info = None
        for name, info in STADIUMS.items():
            if name.lower() in stadium_name.lower() or \
               stadium_name.lower() in name.lower():
                stadium_info = info
                stadium_name = name
                break

        if not stadium_info:
            return WeatherReport(stadium=stadium_name,
                                impact_summary="Stadium coordinates not found")

        report = WeatherReport(stadium=stadium_name, is_dome=stadium_info["dome"])

        if stadium_info["dome"]:
            report.wind_effect = "dome"
            report.impact_summary = "Domed/retractable roof — weather neutral"
            report.total_lean = "neutral"
            return report

        # Fetch weather
        try:
            resp = self.session.get(WEATHER_URL, params={
                "latitude": stadium_info["lat"],
                "longitude": stadium_info["lon"],
                "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "America/New_York",
            }, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            current = data.get("current", {})

            report.temp_f = current.get("temperature_2m")
            report.humidity = current.get("relative_humidity_2m")
            report.precipitation = current.get("precipitation")
            report.wind_speed_mph = current.get("wind_speed_10m")
            report.wind_dir_deg = current.get("wind_direction_10m")

            # Assess wind effect relative to stadium orientation
            report = self._assess_wind(report, stadium_info["cf_bearing"])

        except Exception as e:
            logger.error(f"[Weather] Failed for {stadium_name}: {e}")
            report.impact_summary = "Weather fetch failed"

        return report

    def _assess_wind(self, report: WeatherReport, cf_bearing: float) -> WeatherReport:
        """
        Determine if wind helps or hurts hitters based on direction
        relative to the stadium's home-plate-to-center-field bearing.
        """
        if report.wind_speed_mph is None or report.wind_dir_deg is None:
            report.wind_effect = "unknown"
            return report

        # Wind direction is where wind comes FROM (meteorological)
        # Wind blowing TO = wind_dir + 180
        wind_to = (report.wind_dir_deg + 180) % 360

        # Angle between wind-to direction and center field bearing
        diff = abs((wind_to - cf_bearing + 180) % 360 - 180)

        speed = report.wind_speed_mph

        if speed < 5:
            report.wind_effect = "calm"
            report.impact_summary = f"Light wind ({speed} mph) — minimal effect"
            report.total_lean = "neutral"
        elif diff < 45:
            # Wind blowing OUT toward center
            report.wind_effect = "out"
            report.impact_summary = (f"Wind blowing OUT to CF at {speed} mph — "
                                    f"boosts HRs and scoring")
            report.total_lean = "over" if speed >= 10 else "neutral"
        elif diff > 135:
            # Wind blowing IN from center
            report.wind_effect = "in"
            report.impact_summary = (f"Wind blowing IN from CF at {speed} mph — "
                                    f"suppresses HRs and scoring")
            report.total_lean = "under" if speed >= 10 else "neutral"
        else:
            # Crosswind
            report.wind_effect = "crosswind"
            report.impact_summary = (f"Crosswind at {speed} mph — "
                                    f"unpredictable, affects fly balls")
            report.total_lean = "neutral"

        # Temperature effect (hot air = ball travels farther)
        if report.temp_f is not None:
            if report.temp_f >= 85:
                report.impact_summary += f". Hot ({report.temp_f}°F) — ball carries."
            elif report.temp_f <= 50:
                report.impact_summary += f". Cold ({report.temp_f}°F) — ball dies."

        return report

    def format_for_analysis(self, report: WeatherReport) -> str:
        """Format weather report for AI prompt."""
        if report.is_dome:
            return f"Weather: {report.stadium} is domed — no weather impact."

        lines = [f"Weather at {report.stadium}:"]
        if report.temp_f is not None:
            lines.append(f"  Temp: {report.temp_f}°F | Humidity: {report.humidity}%")
        if report.wind_speed_mph is not None:
            lines.append(f"  Wind: {report.wind_speed_mph} mph, effect: {report.wind_effect}")
        lines.append(f"  Impact: {report.impact_summary}")
        if report.total_lean != "neutral":
            lines.append(f"  Total lean: {report.total_lean.upper()}")
        return "\n".join(lines)
