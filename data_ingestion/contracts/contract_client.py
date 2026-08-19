"""
data_ingestion/contracts/contract_client.py
Scrapes player contract data and incentive clauses from:
- Spotrac (all 4 sports)
- HoopsHype (NBA)
- OverTheCap (NFL)
- CapFriendly (NHL)

Incentive clauses are the #1 betting edge this provides:
A player chasing a performance bonus is MOTIVATED differently.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime
from loguru import logger
from database.models import get_session, Player, PlayerContract
from config.settings import CONTRACT_SOURCES

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


class ContractClient:
    """Scrapes player contract and incentive data."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get_page(self, url: str) -> BeautifulSoup | None:
        """Fetch and parse a web page."""
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.content, "lxml")
        except Exception as e:
            logger.warning(f"[Contract] Failed to fetch {url}: {e}")
            return None

    def _parse_salary(self, salary_str: str) -> float:
        """Convert '$45,000,000' or '$45M' to float."""
        if not salary_str:
            return 0.0
        cleaned = salary_str.replace("$", "").replace(",", "").strip()
        if "M" in cleaned.upper():
            return float(cleaned.upper().replace("M", "")) * 1_000_000
        if "K" in cleaned.upper():
            return float(cleaned.upper().replace("K", "")) * 1_000
        try:
            return float(cleaned)
        except Exception:
            return 0.0

    # ── NBA Contracts (HoopsHype) ──────────────────────────────────────

    def scrape_nba_contracts(self) -> list[dict]:
        """
        Scrape NBA salary data from HoopsHype.
        Returns list of contract dicts.
        """
        url = "https://hoopshype.com/salaries/players/"
        soup = self._get_page(url)
        if not soup:
            return []

        contracts = []
        table = soup.find("table", class_="hh-salaries-ranking-table")
        if not table:
            logger.warning("[Contract] HoopsHype table structure changed — check scraper.")
            return []

        for row in table.find_all("tr")[1:]:  # Skip header
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            player_name = cols[1].get_text(strip=True)
            salary_str  = cols[2].get_text(strip=True)
            salary      = self._parse_salary(salary_str)

            if salary > 0:
                contracts.append({
                    "player_name":   player_name,
                    "sport":         "NBA",
                    "annual_salary": salary,
                    "source_url":    url,
                })

        logger.info(f"[Contract] Scraped {len(contracts)} NBA contracts from HoopsHype.")
        return contracts

    def scrape_spotrac_player(self, sport: str, player_name: str,
                               spotrac_slug: str) -> dict | None:
        """
        Scrape an individual player's contract page on Spotrac.
        spotrac_slug: URL-formatted name e.g. "lebron-james"
        """
        sport_path = {"NBA": "nba", "NFL": "nfl", "MLB": "mlb", "NHL": "nhl"}
        url = f"https://www.spotrac.com/{sport_path[sport]}/player/{spotrac_slug}/"
        soup = self._get_page(url)
        if not soup:
            return None

        contract = {
            "player_name": player_name,
            "sport":       sport,
            "source_url":  url,
            "incentives":  [],
        }

        # Parse basic contract info
        info_divs = soup.find_all("div", class_="contract-line")
        for div in info_divs:
            text = div.get_text(strip=True).lower()
            if "total value" in text:
                match = re.search(r'\$[\d,]+', div.get_text())
                if match:
                    contract["total_value"] = self._parse_salary(match.group())
            elif "years" in text:
                match = re.search(r'(\d+)\s*year', text)
                if match:
                    contract["years"] = int(match.group(1))

        # Parse incentive clauses — THE KEY BETTING EDGE
        incentive_section = (soup.find("div", class_="incentives") or
                             soup.find("section", id="incentives") or
                             soup.find("table", class_="incentive"))

        if incentive_section:
            incentive_text = incentive_section.get_text(separator="\n")
            contract["incentive_summary"] = incentive_text[:2000]

            # Try to parse structured incentive data
            for row in incentive_section.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) >= 2:
                    desc   = cols[0].get_text(strip=True)
                    amount = cols[-1].get_text(strip=True)

                    incentive = {
                        "description":   desc,
                        "bonus_amount":  self._parse_salary(amount),
                        "likely":        "likely" in desc.lower(),
                    }

                    # Parse stat thresholds from description
                    # e.g. "If player averages 25+ PPG" → stat=points, threshold=25
                    stat_patterns = [
                        (r'(\d+)\+?\s*points?\s*per game', "points_per_game"),
                        (r'(\d+)\+?\s*ppg',                "points_per_game"),
                        (r'(\d+)\+?\s*rebounds?\s*per game',"rebounds_per_game"),
                        (r'(\d+)\+?\s*assists?\s*per game', "assists_per_game"),
                        (r'(\d+)\+?\s*games?\s*played',    "games_played"),
                        (r'(\d+)\+?\s*passing yards',      "passing_yards"),
                        (r'(\d+)\+?\s*rushing yards',      "rushing_yards"),
                        (r'(\d+)\+?\s*touchdowns',         "touchdowns"),
                        (r'(\d+)\+?\s*strikeouts',         "strikeouts"),
                        (r'(\d+)\+?\s*goals',              "goals"),
                    ]
                    for pattern, stat_name in stat_patterns:
                        match = re.search(pattern, desc.lower())
                        if match:
                            incentive["stat"]      = stat_name
                            incentive["threshold"] = float(match.group(1))
                            break

                    contract["incentives"].append(incentive)

        return contract

    # ── NFL Contracts (OverTheCap) ─────────────────────────────────────

    def scrape_nfl_contracts_otc(self) -> list[dict]:
        """
        Scrape NFL contract overview from OverTheCap.
        """
        url = "https://overthecap.com/contracts"
        soup = self._get_page(url)
        if not soup:
            return []

        contracts = []
        table = soup.find("table", id="contracts-table")
        if not table:
            return []

        for row in table.find("tbody", {}).find_all("tr") if table.find("tbody") else []:
            cols = row.find_all("td")
            if len(cols) < 5:
                continue
            contracts.append({
                "player_name":   cols[0].get_text(strip=True),
                "sport":         "NFL",
                "contract_type": cols[2].get_text(strip=True),
                "total_value":   self._parse_salary(cols[3].get_text(strip=True)),
                "annual_salary": self._parse_salary(cols[4].get_text(strip=True)),
                "source_url":    url,
                "incentives":    [],
            })

        logger.info(f"[Contract] Scraped {len(contracts)} NFL contracts from OTC.")
        return contracts

    # ── Match & Save Contracts ─────────────────────────────────────────

    def match_and_save_contracts(self, sport: str, contracts_data: list[dict]):
        """
        Match scraped contract data to players in the DB and save.
        Uses fuzzy name matching since names may differ slightly.
        """
        db = get_session()
        try:
            saved = unmatched = 0

            for contract in contracts_data:
                player_name = contract.get("player_name", "")
                if not player_name:
                    continue

                # Try exact match first
                player = (db.query(Player)
                          .filter(Player.sport == sport,
                                  Player.full_name == player_name)
                          .first())

                # Try last name if exact fails
                if not player:
                    last_name = player_name.split()[-1] if player_name.split() else ""
                    player = (db.query(Player)
                              .filter(Player.sport == sport,
                                      Player.last_name == last_name)
                              .first())

                if not player:
                    unmatched += 1
                    continue

                # Build contract record
                existing = (db.query(PlayerContract)
                            .filter_by(player_id=player.player_id)
                            .first())

                contract_data = {
                    "player_id":        player.player_id,
                    "sport":            sport,
                    "annual_salary":    contract.get("annual_salary", 0),
                    "total_value":      contract.get("total_value", 0),
                    "years":            contract.get("years", 0),
                    "contract_type":    contract.get("contract_type", ""),
                    "incentives":       contract.get("incentives", []),
                    "incentive_summary": contract.get("incentive_summary", ""),
                    "source_url":       contract.get("source_url", ""),
                    "updated_at":       datetime.utcnow(),
                }

                if existing:
                    for k, v in contract_data.items():
                        setattr(existing, k, v)
                else:
                    db.add(PlayerContract(**contract_data))
                saved += 1

            db.commit()
            logger.info(f"[Contract] ✅ {sport}: {saved} contracts saved, "
                        f"{unmatched} players unmatched.")
        except Exception as e:
            db.rollback()
            logger.error(f"[Contract] Save failed for {sport}: {e}")
        finally:
            db.close()

    def get_players_with_incentives(self, sport: str) -> list[dict]:
        """
        Get players who have active incentive clauses.
        Returns formatted data for the AI analysis layer.
        """
        db = get_session()
        try:
            contracts = (db.query(PlayerContract)
                         .filter(PlayerContract.sport == sport)
                         .filter(PlayerContract.incentives != None)
                         .all())

            results = []
            for c in contracts:
                if c.incentives and len(c.incentives) > 0:
                    player = db.query(Player).filter_by(
                        player_id=c.player_id
                    ).first()
                    if player:
                        results.append({
                            "player_name":   player.full_name,
                            "player_id":     player.player_id,
                            "team":          player.team_id,
                            "incentives":    c.incentives,
                            "annual_salary": c.annual_salary,
                        })
            return results
        finally:
            db.close()

    def run_sport(self, sport: str):
        """Scrape and save contracts for a sport."""
        logger.info(f"[Contract] Starting {sport} contract scrape...")

        if sport == "NBA":
            contracts = self.scrape_nba_contracts()
            self.match_and_save_contracts(sport, contracts)

        elif sport == "NFL":
            contracts = self.scrape_nfl_contracts_otc()
            self.match_and_save_contracts(sport, contracts)

        # MLB and NHL: use Spotrac generic approach
        # (Individual player pages need to be triggered from player list)
        else:
            logger.info(f"[Contract] {sport}: Individual player Spotrac scraping "
                        f"triggered from player list (runs in background).")

    def run_all_sports(self):
        """Scrape contracts for all sports."""
        for sport in ["NBA", "NFL", "MLB", "NHL"]:
            self.run_sport(sport)


if __name__ == "__main__":
    client = ContractClient()
    client.run_all_sports()
