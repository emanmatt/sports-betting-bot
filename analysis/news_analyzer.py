"""
analysis/news_analyzer.py

Analyzes news for betting signals AND automatically fills data gaps
using web search. No manual intervention needed.

Pipeline:
1. Pull news from DB
2. Get today's schedule from OddsAPI
3. AI analyzes news vs schedule
4. Extract flagged data gaps from AI output
5. Auto-search web to fill each gap (starters, bullpen, injuries)
6. Feed web results back to AI for final verdict
7. Output complete analysis with no manual steps
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
import re
from datetime import datetime, timedelta
from loguru import logger
from database.models import get_session, NewsArticle
from config.settings import ANTHROPIC_API_KEY

MODEL = "claude-sonnet-4-6"


class NewsAnalyzer:

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def get_recent_news(self, sport: str, hours: int = 48) -> list:
        db = get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            return (db.query(NewsArticle)
                    .filter(NewsArticle.sport == sport,
                            NewsArticle.published_at >= cutoff)
                    .order_by(NewsArticle.published_at.desc())
                    .limit(30)
                    .all())
        finally:
            db.close()

    def _get_todays_schedule(self, sport: str) -> tuple[str, list]:
        """Returns (formatted string, list of game dicts)."""
        try:
            from data_ingestion.official.schedule_engine import ScheduleEngine
            engine = ScheduleEngine()
            games = engine.get_todays_games(sport)
            if not games:
                return f"No {sport} games today.", []
            lines = [f"Today's {sport} games ({len(games)}):"]
            for g in games:
                line = f"  {g['away_team']} @ {g['home_team']} — {g['game_time_et']}"
                if g.get("spread") is not None:
                    line += f" | Spread {g['spread']:+.1f} | O/U {g.get('total','?')}"
                lines.append(line)
            return "\n".join(lines), games
        except Exception as e:
            return f"Schedule unavailable: {e}", []

    def _extract_data_gaps(self, analysis_text: str) -> list[str]:
        """Pull the MISSING INFORMATION section from AI output."""
        section = re.search(
            r"MISSING INFORMATION[:\s]*(.*?)(?=OVERALL SIGNAL|$)",
            analysis_text, re.DOTALL | re.IGNORECASE
        )
        if not section:
            return []
        gaps = []
        for line in section.group(1).split("\n"):
            line = line.strip("- •*0123456789.").strip()
            if line and len(line) > 10:
                gaps.append(line)
        return gaps[:8]

    def _extract_flagged_teams(self, analysis_text: str) -> list[str]:
        flagged = []
        team_section = re.search(
            r"TEAM FLAGS[:\s]*(.*?)(?=MISSING|OVERALL|$)",
            analysis_text, re.DOTALL | re.IGNORECASE
        )
        if team_section:
            names = re.findall(
                r"\*\*([A-Z][a-zA-Z ]+?)\*\*",
                team_section.group(1)
            )
            flagged.extend(names)
        seen = set()
        unique = []
        for name in flagged:
            name = name.strip()
            if name.lower() not in seen and len(name) > 3:
                seen.add(name.lower())
                unique.append(name)
        return unique[:5]

    def _get_next_game_context(self, team_name: str, sport: str) -> str:
        try:
            from data_ingestion.official.schedule_engine import ScheduleEngine
            engine = ScheduleEngine()
            game = engine.get_team_next_game(team_name, sport)
            if not game:
                return f"  {team_name}: No upcoming game found"
            lines = [
                f"  Next: {game['away_team']} @ {game['home_team']} — {game['game_time_et']}",
            ]
            if game.get("spread") is not None:
                lines.append(f"  Lines: Spread {game['spread']:+.1f} | "
                           f"Total {game.get('total','?')} | "
                           f"ML Home {game.get('home_ml','?')} / Away {game.get('away_ml','?')}")
            return "\n".join(lines)
        except Exception:
            return f"  {team_name}: Schedule lookup unavailable"

    def _auto_search_gaps(self, gaps: list[str], games: list[dict],
                           sport: str) -> str:
        """
        Automatically search the web for every flagged data gap.
        No manual intervention needed.
        """
        if not gaps:
            return ""

        try:
            from data_ingestion.soft.web_search import WebSearchEngine
            searcher = WebSearchEngine()
        except Exception as e:
            logger.warning(f"[NewsAnalyzer] Web search unavailable: {e}")
            return ""

        all_findings = []

        for game in games[:4]:  # Check top 4 games
            home = game.get("home_team", "")
            away = game.get("away_team", "")

            # Check if any gap relates to this game's teams
            game_gaps = [
                g for g in gaps
                if any(team_word in g
                       for t in [home, away]
                       for team_word in t.split())
            ]

            # Also include generic gaps (starters, bullpen)
            generic_gaps = [
                g for g in gaps
                if not any(
                    any(team_word in g for team_word in t.split())
                    for t in [home, away]
                )
            ]

            if game_gaps or generic_gaps:
                relevant_gaps = (game_gaps + generic_gaps)[:4]
                findings = searcher.auto_fill_data_gaps(
                    sport, home, away, relevant_gaps
                )
                formatted = searcher.format_findings_for_prompt(findings)
                if "No web search results" not in formatted:
                    all_findings.append(
                        f"\n{away} @ {home}:\n{formatted}"
                    )

        return "\n".join(all_findings) if all_findings else ""

    def analyze_news_for_sport(self, sport: str) -> str:
        articles = self.get_recent_news(sport, hours=48)
        if not articles:
            return f"No recent {sport} news in database."

        news_text = "\n".join([
            f"[{a.source}] [{a.published_at.strftime('%m/%d %H:%M')}] "
            f"{a.title} — Impact: {a.betting_impact}"
            for a in articles
        ])

        schedule_text, games = self._get_todays_schedule(sport)

        # ── Step 1: Initial analysis ──────────────────────────────────
        prompt_1 = f"""Analyze {sport} news for betting signals. Be honest — say NO BET if nothing is actionable.

TODAY'S SCHEDULE:
{schedule_text}

NEWS (last 48hrs):
{news_text}

Format EXACTLY as:

HIGH IMPACT STORIES:
[only stories affecting today's games]

PLAYER FLAGS:
[Player Name (Team) — specific concern]

TEAM FLAGS:
[**Team Name** — issue — affects today? YES/NO]

MISSING INFORMATION:
[specific facts needed before betting — be precise, e.g. "Milwaukee's starting pitcher for Aug 19" not vague]

OVERALL SIGNAL:
[1-2 sentences on actionable edges]"""

        try:
            from analysis.system_prompt import NEWS_SYSTEM_PROMPT
            r1 = self.client.messages.create(
                model=MODEL,
                max_tokens=1200,
                system=NEWS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt_1}]
            )
            analysis_1 = r1.content[0].text
        except Exception as e:
            return f"Analysis failed: {e}"

        # ── Step 2: Extract gaps and auto-search ──────────────────────
        gaps = self._extract_data_gaps(analysis_1)
        web_findings = ""

        if gaps and games:
            logger.info(f"[NewsAnalyzer] Auto-searching {len(gaps)} data gaps...")
            web_findings = self._auto_search_gaps(gaps, games, sport)

        # ── Step 3: Final verdict with web data ───────────────────────
        if web_findings:
            prompt_2 = f"""You previously identified these data gaps for {sport}:
{chr(10).join(f'- {g}' for g in gaps)}

The bot automatically searched the web and found:
{web_findings}

Using this new information, provide a FINAL VERDICT:

STARTER CONFIRMED:
[Who is starting for each relevant team — confirmed or still unknown]

BULLPEN STATUS:
[Available / Depleted / Unknown for each relevant team]

INJURY STATUS:
[Any players with updated status]

FINAL BET RECOMMENDATION:
[Specific bet or NO BET — with exact reasoning using the new data]
Confidence: [1-10]
Units: [0 / 0.5 / 1 / 2]

REMAINING UNKNOWNS:
[Anything still not confirmed that could change this]"""

            try:
                r2 = self.client.messages.create(
                    model=MODEL,
                    max_tokens=600,
                    messages=[{"role": "user", "content": prompt_2}]
                )
                final_verdict = r2.content[0].text
            except Exception as e:
                final_verdict = f"Final verdict failed: {e}"
        else:
            final_verdict = ""

        # ── Step 4: Auto-enrich with next game schedule ───────────────
        flagged_teams = self._extract_flagged_teams(analysis_1)
        schedule_enrichment = ""
        if flagged_teams:
            lines = ["\nNEXT GAME AUTO-LOOKUP:"]
            for team in flagged_teams:
                lines.append(f"{team}:")
                lines.append(self._get_next_game_context(team, sport))
            schedule_enrichment = "\n".join(lines)

        # ── Combine all sections ──────────────────────────────────────
        output = analysis_1

        if web_findings:
            output += f"\n\n{'='*50}\nAUTO WEB SEARCH RESULTS:\n{'='*50}\n{web_findings}"

        if final_verdict:
            output += f"\n\n{'='*50}\nFINAL VERDICT (after auto-research):\n{'='*50}\n{final_verdict}"

        if schedule_enrichment:
            output += f"\n{schedule_enrichment}"

        return output

    def run_daily_news_scan(self) -> dict:
        results = {}
        db = get_session()
        try:
            sports_with_news = db.query(NewsArticle.sport).distinct().all()
            sports = [s[0] for s in sports_with_news]
        finally:
            db.close()

        for sport in sports:
            logger.info(f"[NewsAnalyzer] Analyzing {sport}...")
            results[sport] = self.analyze_news_for_sport(sport)
            logger.info(f"[NewsAnalyzer] ✅ {sport} done.")

        return results

    def get_game_brief(self, home_team: str, away_team: str, sport: str) -> str:
        try:
            from data_ingestion.official.schedule_engine import ScheduleEngine
            engine = ScheduleEngine()
            brief = engine.build_game_brief(home_team, away_team, sport)

            # Auto-search starters and key gaps
            gaps = [
                f"{home_team} starting pitcher today",
                f"{away_team} starting pitcher today",
                f"{away_team} bullpen usage yesterday",
            ]
            try:
                from data_ingestion.soft.web_search import WebSearchEngine
                searcher = WebSearchEngine()
                findings = searcher.auto_fill_data_gaps(
                    sport, home_team, away_team, gaps
                )
                web_text = searcher.format_findings_for_prompt(findings)
                if "No web search results" not in web_text:
                    brief += f"\n\n{'='*50}\nAUTO-SEARCHED:\n{'='*50}\n{web_text}"
            except Exception as e:
                logger.debug(f"Web search skipped: {e}")

            return brief
        except Exception as e:
            return f"Brief failed: {e}"
