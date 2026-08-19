"""
data_ingestion/soft/web_search.py

Automatically searches the web using Claude's built-in web_search tool.
This is the most reliable approach — Claude searches the live web
and returns structured results, no scraping needed.

Automatically finds:
- Confirmed starting pitchers / starters
- Bullpen usage from previous games  
- Last-minute injury updates
- Lineup confirmations
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import anthropic
import re
from datetime import datetime
from loguru import logger
from config.settings import ANTHROPIC_API_KEY

MODEL = "claude-sonnet-4-6"
TODAY = datetime.utcnow().strftime("%B %d %Y")  # "August 19 2026"


class WebSearchEngine:
    """
    Uses Claude's web_search tool to automatically find
    betting-relevant information without any manual lookups.
    """

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def search_and_extract(self, query: str,
                           extraction_prompt: str) -> str:
        """
        Search the web using Claude's tool and extract specific info.
        query: what to search for
        extraction_prompt: what specific info to pull from results
        """
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=500,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                system=(
                    "You are a sports data researcher. Search for the specific "
                    "information requested and return ONLY the factual answer. "
                    "Be concise. If you cannot find definitive information, "
                    "say 'Not confirmed' — never guess or assume."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Search for: {query}\n\n"
                        f"Extract and return only: {extraction_prompt}\n"
                        f"Today's date: {TODAY}"
                    )
                }]
            )

            # Extract text from response (may include tool use blocks)
            result_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    result_text += block.text

            return result_text.strip() or "Not found"

        except Exception as e:
            logger.debug(f"[WebSearch] Search failed for '{query}': {e}")
            return "Search unavailable"

    def get_probable_starter(self, team: str, sport: str,
                             game_date: str = None) -> dict:
        """Find confirmed starting pitcher/starter for a team today."""
        date_str = game_date or TODAY

        sport_term = {
            "MLB": "starting pitcher",
            "NFL": "starting quarterback",
            "NBA": "starting lineup",
            "NHL": "starting goalie",
        }.get(sport, "starter")

        query = f"{team} {sport_term} {date_str}"
        extraction = (
            f"The confirmed {sport_term} for {team} on {date_str}. "
            f"Return: player name, handedness if pitcher (LHP/RHP), "
            f"and whether they are confirmed or listed as probable."
        )

        result = self.search_and_extract(query, extraction)
        confirmed = "Not confirmed" not in result and "Not found" not in result

        return {
            "found": confirmed,
            "starter": result,
            "confidence": "high" if confirmed else "low",
        }

    def get_bullpen_usage(self, team: str,
                          game_date: str = None) -> dict:
        """Find how many pitchers a team used in their last game."""
        # Search for yesterday's box score
        query = f"{team} pitchers used box score {game_date or TODAY}"
        extraction = (
            f"How many relief pitchers did {team} use? "
            f"List pitcher names and innings/pitches if available. "
            f"Is their bullpen considered depleted or rested for today?"
        )

        result = self.search_and_extract(query, extraction)

        return {
            "team": team,
            "usage_info": result,
            "is_depleted": any(word in result.lower() for word in
                              ["depleted", "taxed", "heavily used", "9 pitchers",
                               "8 pitchers", "7 pitchers", "blowout"])
        }

    def get_injury_update(self, player_name: str,
                          team: str) -> dict:
        """Get latest injury status for a player."""
        query = f"{player_name} {team} injury status {TODAY}"
        extraction = (
            f"Current injury/availability status of {player_name}. "
            f"Return: status (Out/Doubtful/Questionable/Active), "
            f"injury type, and expected return date if known."
        )

        result = self.search_and_extract(query, extraction)

        status = "Unknown"
        for kw in ["out", "doubtful", "questionable", "active",
                   "activated", "IL", "day-to-day", "cleared"]:
            if kw.lower() in result.lower():
                status = kw.title()
                break

        return {
            "player": player_name,
            "status": status,
            "details": result,
        }

    def get_lineup_confirmation(self, team: str, sport: str) -> dict:
        """Check if lineup has been officially posted."""
        query = f"{team} official lineup {TODAY} {sport}"
        extraction = (
            f"Has {team}'s official starting lineup been posted for today? "
            f"List any confirmed starters if available."
        )

        result = self.search_and_extract(query, extraction)
        confirmed = any(word in result.lower()
                       for word in ["confirmed", "official", "announced", "posted"])

        return {
            "team": team,
            "confirmed": confirmed,
            "details": result,
        }

    def auto_fill_data_gaps(self, sport: str,
                            home_team: str,
                            away_team: str,
                            flagged_gaps: list[str]) -> dict:
        """
        Main method — takes flagged data gaps and searches each one.
        Called automatically by the analysis pipeline.
        """
        findings = {
            "home_team": home_team,
            "away_team": away_team,
            "sport": sport,
            "searched_at": datetime.utcnow().isoformat(),
            "results": {},
        }

        logger.info(f"[WebSearch] Auto-searching {len(flagged_gaps)} gaps "
                   f"for {away_team} @ {home_team}...")

        for gap in flagged_gaps:
            gap_lower = gap.lower()

            # Starter searches
            if any(w in gap_lower for w in
                   ["starter", "pitcher", "starting pitcher",
                    "arm", "goalie", "qb", "quarterback"]):
                for team in [home_team, away_team]:
                    key = f"{team}_starter"
                    if key not in findings["results"]:
                        logger.info(f"[WebSearch] Searching starter: {team}")
                        findings["results"][key] = self.get_probable_starter(
                            team, sport
                        )

            # Bullpen usage
            elif any(w in gap_lower for w in
                     ["bullpen", "relievers", "pitchers used",
                      "arms available", "usage"]):
                for team in [home_team, away_team]:
                    if any(t in gap_lower for t in
                           team.lower().split() + ["both", "mariners", "brewers"]):
                        key = f"{team}_bullpen"
                        if key not in findings["results"]:
                            logger.info(f"[WebSearch] Searching bullpen: {team}")
                            findings["results"][key] = self.get_bullpen_usage(team)

            # Injury updates
            elif any(w in gap_lower for w in
                     ["injury", "status", "health", "availability", "il", "scratched"]):
                name_match = re.search(
                    r"([A-Z][a-z]+(?:'s)?\s+[A-Z][a-z]+)", gap
                )
                if name_match:
                    player = name_match.group(1).replace("'s", "").strip()
                    team = (home_team if any(t in gap_lower for t in
                                           home_team.lower().split())
                           else away_team)
                    key = f"{player.replace(' ','_')}_injury"
                    if key not in findings["results"]:
                        logger.info(f"[WebSearch] Searching injury: {player}")
                        findings["results"][key] = self.get_injury_update(
                            player, team
                        )

            # Lineup
            elif "lineup" in gap_lower:
                for team in [home_team, away_team]:
                    if any(t in gap_lower for t in team.lower().split()):
                        key = f"{team}_lineup"
                        if key not in findings["results"]:
                            logger.info(f"[WebSearch] Searching lineup: {team}")
                            findings["results"][key] = self.get_lineup_confirmation(
                                team, sport
                            )

        logger.info(f"[WebSearch] ✅ Completed {len(findings['results'])} searches.")
        return findings

    def format_findings_for_prompt(self, findings: dict) -> str:
        """Format web findings for AI prompt."""
        if not findings.get("results"):
            return "No web search results available."

        lines = [f"WEB SEARCH RESULTS (auto-searched at "
                f"{findings.get('searched_at','?')[:16]}):"]

        for key, result in findings["results"].items():
            label = key.replace("_", " ").upper()
            lines.append(f"\n► {label}:")

            if "starter" in key:
                lines.append(f"  {result.get('starter', 'Not confirmed')}")
                lines.append(f"  Confidence: {result.get('confidence','?')}")

            elif "bullpen" in key:
                lines.append(f"  {result.get('usage_info', 'Unknown')}")
                if result.get("is_depleted"):
                    lines.append("  ⚠️ BULLPEN FLAGGED AS DEPLETED")

            elif "injury" in key:
                lines.append(f"  Status: {result.get('status', 'Unknown')}")
                lines.append(f"  {result.get('details', '')[:200]}")

            elif "lineup" in key:
                conf = result.get("confirmed", False)
                lines.append(f"  Lineup confirmed: {'YES' if conf else 'NOT YET'}")
                if result.get("details"):
                    lines.append(f"  {result['details'][:200]}")

        return "\n".join(lines)