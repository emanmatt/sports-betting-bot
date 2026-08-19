"""
data_ingestion/official/espn_client.py
Pulls teams, players, scores, schedules, and injury reports
from ESPN's unofficial (but free and stable) API.
Covers: NBA, NFL, MLB, NHL
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
import time
import random
from datetime import datetime
from loguru import logger
from database.models import get_session, Team, Player, Game, InjuryReport
from config.settings import ESPN_SPORT_CONFIG, SUPPORTED_SPORTS

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"

# Rotate through real browser user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


class ESPNClient:
    """Pulls all available data from ESPN's free API."""

    def __init__(self):
        self.session = requests.Session()
        self._rotate_headers()

    def _rotate_headers(self):
        """Rotate user agent and set realistic browser headers."""
        ua = random.choice(USER_AGENTS)
        self.session.headers.update({
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://www.espn.com/",
            "Origin": "https://www.espn.com",
            "sec-ch-ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        })

    def _get(self, url: str, params: dict = None) -> dict:
        """Make a GET request with retry logic and delays."""
        self._rotate_headers()
        for attempt in range(3):
            try:
                # Random delay between requests to avoid rate limiting
                time.sleep(random.uniform(1.5, 3.5))
                resp = self.session.get(url, params=params, timeout=20)
                if resp.status_code == 403:
                    logger.warning(f"[ESPN] 403 blocked on attempt {attempt+1}, waiting...")
                    time.sleep(10 + attempt * 5)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
        raise Exception("Max retries exceeded")

    # ── Teams ─────────────────────────────────────────────────────────

    def fetch_teams(self, sport: str) -> list[dict]:
        cfg = ESPN_SPORT_CONFIG[sport]
        url = f"{BASE_URL}/{cfg['sport']}/{cfg['league']}/teams"
        data = self._get(url, params={"limit": 100})

        teams = []
        for item in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
            t = item.get("team", {})
            teams.append({
                "sport":        sport,
                "league":       cfg["league"].upper(),
                "team_id":      f"{sport}_{t.get('id', '')}",
                "name":         t.get("displayName", ""),
                "abbreviation": t.get("abbreviation", ""),
                "city":         t.get("location", ""),
                "logo_url":     t.get("logos", [{}])[0].get("href", "") if t.get("logos") else "",
            })
        logger.info(f"[ESPN] Fetched {len(teams)} {sport} teams.")
        return teams

    def save_teams(self, sport: str):
        db = get_session()
        try:
            teams_data = self.fetch_teams(sport)
            for td in teams_data:
                existing = db.query(Team).filter_by(team_id=td["team_id"]).first()
                if existing:
                    for k, v in td.items():
                        setattr(existing, k, v)
                    existing.updated_at = datetime.utcnow()
                else:
                    db.add(Team(**td))
            db.commit()
            logger.info(f"[ESPN] ✅ Saved {len(teams_data)} {sport} teams to DB.")
        except Exception as e:
            db.rollback()
            logger.error(f"[ESPN] Failed to save {sport} teams: {e}")
        finally:
            db.close()

    # ── Players ───────────────────────────────────────────────────────

    def fetch_players_for_team(self, sport: str, espn_team_id: str) -> list[dict]:
        cfg = ESPN_SPORT_CONFIG[sport]
        url = f"{BASE_URL}/{cfg['sport']}/{cfg['league']}/teams/{espn_team_id}/roster"
        try:
            data = self._get(url)
        except Exception as e:
            logger.warning(f"[ESPN] Could not fetch roster for team {espn_team_id}: {e}")
            return []

        players = []
        for group in data.get("athletes", []):
            items = group.get("items", []) if isinstance(group, dict) else [group]
            for p in items:
                players.append({
                    "sport":          sport,
                    "player_id":      f"{sport}_{p.get('id', '')}",
                    "team_id":        f"{sport}_{espn_team_id}",
                    "full_name":      p.get("fullName", ""),
                    "first_name":     p.get("firstName", ""),
                    "last_name":      p.get("lastName", ""),
                    "position":       p.get("position", {}).get("abbreviation", ""),
                    "jersey_number":  p.get("jersey", ""),
                    "height":         p.get("displayHeight", ""),
                    "weight":         p.get("weight", 0),
                    "age":            p.get("age", 0),
                    "date_of_birth":  p.get("dateOfBirth", ""),
                    "years_experience": p.get("experience", {}).get("years", 0),
                    "college":        p.get("college", {}).get("name", "") if p.get("college") else "",
                    "draft_year":     p.get("draft", {}).get("year", 0) if p.get("draft") else 0,
                    "draft_round":    p.get("draft", {}).get("round", 0) if p.get("draft") else 0,
                    "draft_pick":     p.get("draft", {}).get("selection", 0) if p.get("draft") else 0,
                    "status":         p.get("status", {}).get("name", "Active") if p.get("status") else "Active",
                    "headshot_url":   p.get("headshot", {}).get("href", "") if p.get("headshot") else "",
                })
        return players

    def save_all_players(self, sport: str):
        db = get_session()
        try:
            teams = db.query(Team).filter_by(sport=sport).all()
            total_saved = 0
            for team in teams:
                espn_id = team.team_id.split("_", 1)[1]
                players_data = self.fetch_players_for_team(sport, espn_id)
                for pd in players_data:
                    existing = db.query(Player).filter_by(player_id=pd["player_id"]).first()
                    if existing:
                        for k, v in pd.items():
                            setattr(existing, k, v)
                        existing.updated_at = datetime.utcnow()
                    else:
                        db.add(Player(**pd))
                    total_saved += 1
            db.commit()
            logger.info(f"[ESPN] ✅ Saved {total_saved} {sport} players to DB.")
        except Exception as e:
            db.rollback()
            logger.error(f"[ESPN] Failed to save {sport} players: {e}")
        finally:
            db.close()

    # ── Schedule & Games ──────────────────────────────────────────────

    def fetch_schedule(self, sport: str, dates: str = None) -> list[dict]:
        cfg = ESPN_SPORT_CONFIG[sport]
        url = f"{BASE_URL}/{cfg['sport']}/{cfg['league']}/scoreboard"
        params = {}
        if dates:
            params["dates"] = dates

        data = self._get(url, params=params)
        games = []

        for event in data.get("events", []):
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})

            game_date_str = event.get("date", "")
            try:
                game_date = datetime.fromisoformat(game_date_str.replace("Z", "+00:00"))
            except Exception:
                game_date = datetime.utcnow()

            status_obj = event.get("status", {})
            status_type = status_obj.get("type", {}).get("name", "Scheduled")
            status_map = {
                "STATUS_SCHEDULED":   "Scheduled",
                "STATUS_IN_PROGRESS": "InProgress",
                "STATUS_FINAL":       "Final",
                "STATUS_HALFTIME":    "InProgress",
            }
            venue = comp.get("venue", {})

            games.append({
                "sport":        sport,
                "game_id":      f"{sport}_{event.get('id', '')}",
                "home_team_id": f"{sport}_{home.get('team', {}).get('id', '')}",
                "away_team_id": f"{sport}_{away.get('team', {}).get('id', '')}",
                "game_date":    game_date,
                "season_year":  event.get("season", {}).get("year", datetime.utcnow().year),
                "season_type":  event.get("season", {}).get("type", {}).get("name", "Regular"),
                "status":       status_map.get(status_type, "Scheduled"),
                "home_score":   int(home.get("score", 0) or 0),
                "away_score":   int(away.get("score", 0) or 0),
                "venue_name":   venue.get("fullName", ""),
                "venue_city":   venue.get("address", {}).get("city", ""),
                "broadcast":    comp.get("broadcasts", [{}])[0].get("names", [""])[0] if comp.get("broadcasts") else "",
            })

        logger.info(f"[ESPN] Fetched {len(games)} {sport} games.")
        return games

    def save_schedule(self, sport: str, dates: str = None):
        db = get_session()
        try:
            games_data = self.fetch_schedule(sport, dates)
            for gd in games_data:
                existing = db.query(Game).filter_by(game_id=gd["game_id"]).first()
                if existing:
                    for k, v in gd.items():
                        setattr(existing, k, v)
                    existing.updated_at = datetime.utcnow()
                else:
                    db.add(Game(**gd))
            db.commit()
            logger.info(f"[ESPN] ✅ Saved {len(games_data)} {sport} games to DB.")
        except Exception as e:
            db.rollback()
            logger.error(f"[ESPN] Failed to save {sport} schedule: {e}")
        finally:
            db.close()

    # ── Injuries ──────────────────────────────────────────────────────

    def fetch_injuries(self, sport: str) -> list[dict]:
        cfg = ESPN_SPORT_CONFIG[sport]
        url = f"{BASE_URL}/{cfg['sport']}/{cfg['league']}/injuries"
        try:
            data = self._get(url)
        except Exception as e:
            logger.warning(f"[ESPN] Injury fetch failed for {sport}: {e}")
            return []

        injuries = []
        for team_entry in data.get("injuries", []):
            for injury in team_entry.get("injuries", []):
                athlete = injury.get("athlete", {})
                injuries.append({
                    "player_id":   f"{sport}_{athlete.get('id', '')}",
                    "sport":       sport,
                    "report_date": datetime.utcnow(),
                    "status":      injury.get("status", ""),
                    "injury_type": injury.get("type", {}).get("name", "") if injury.get("type") else "",
                    "body_part":   injury.get("location", ""),
                    "notes":       injury.get("longComment", ""),
                    "source":      "ESPN",
                    "captured_at": datetime.utcnow(),
                })
        logger.info(f"[ESPN] Fetched {len(injuries)} {sport} injury reports.")
        return injuries

    def save_injuries(self, sport: str):
        db = get_session()
        try:
            injury_data = self.fetch_injuries(sport)
            for inj in injury_data:
                player = db.query(Player).filter_by(player_id=inj["player_id"]).first()
                if not player:
                    continue
                player.injury_status = inj["status"]
                player.injury_detail = inj["notes"]
                db.add(InjuryReport(**inj))
            db.commit()
            logger.info(f"[ESPN] ✅ Saved {len(injury_data)} {sport} injury reports.")
        except Exception as e:
            db.rollback()
            logger.error(f"[ESPN] Failed to save {sport} injuries: {e}")
        finally:
            db.close()

    # ── Full Refresh ──────────────────────────────────────────────────

    def run_full_refresh(self, sport: str):
        logger.info(f"[ESPN] Starting full refresh for {sport}...")
        self.save_teams(sport)
        self.save_all_players(sport)
        self.save_schedule(sport)
        self.save_injuries(sport)
        logger.info(f"[ESPN] ✅ Full refresh complete for {sport}.")

    def run_all_sports(self):
        for sport in SUPPORTED_SPORTS:
            self.run_full_refresh(sport)


if __name__ == "__main__":
    client = ESPNClient()
    client.run_all_sports()