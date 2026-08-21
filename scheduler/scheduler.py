"""
scheduler/scheduler.py
Runs all data pipelines automatically 24/7.
Now includes props and AI signals — fully automatic, no manual runs needed.

Schedule:
  - Schedule (OddsAPI): every 30 min
  - Odds:     every 30 min (conserve free tier credits)
  - News RSS: every 30 min
  - Props:    every 2 hours (game day only)
  - AI News Analysis: every 3 hours
  - Injuries: every hour
  - Contracts: once per day
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from datetime import datetime
from config.settings import SUPPORTED_SPORTS


def job_update_schedule():
    """Pull game schedules from OddsAPI. Runs every 30 min."""
    from data_ingestion.official.schedule_engine import ScheduleEngine
    logger.info("[Scheduler] 📅 Updating game schedules...")
    engine = ScheduleEngine()
    engine.run_full_schedule_load()


def job_update_odds():
    """Update live odds. Runs every 30 min."""
    from data_ingestion.official.odds_client import OddsClient
    logger.info("[Scheduler] ⚡ Updating odds...")
    client = OddsClient()
    client.run_all_sports()


def job_update_news():
    """Pull RSS news feeds. Runs every 30 min."""
    from data_ingestion.soft.news_client import NewsClient
    logger.info("[Scheduler] 📰 Updating news...")
    client = NewsClient()
    client.run_all_sports()


def job_update_injuries():
    """Pull injury reports. Runs every hour."""
    from data_ingestion.official.espn_client import ESPNClient
    logger.info("[Scheduler] 🏥 Updating injuries...")
    client = ESPNClient()
    for sport in SUPPORTED_SPORTS:
        try:
            client.save_injuries(sport)
        except Exception as e:
            logger.warning(f"[Scheduler] Injury update failed for {sport}: {e}")


def job_update_props():
    """
    Fetch player props and save edges to database.
    Runs every 2 hours. Fully automatic — no manual run needed.
    """
    logger.info("[Scheduler] 🎯 Running props analysis...")
    try:
        from data_ingestion.official.props_engine import PropsEngine
        from database.models import get_session, PropEdgeDB
        engine = PropsEngine()
        db = get_session()

        for sport in SUPPORTED_SPORTS:
            try:
                edges = engine.analyze_props(sport, search_web=False)
                if not edges:
                    continue

                # Clear old props for this sport
                db.query(PropEdgeDB).filter_by(sport=sport).delete()

                # Save new edges
                saved = 0
                for edge in edges:
                    # Mark top 3 as best bets
                    is_best = saved < 3 and edge.edge_strength >= 5.0

                    db_edge = PropEdgeDB(
                        sport=edge.sport,
                        game_id=edge.game_id,
                        player_name=edge.player_name,
                        team=edge.team,
                        opponent=edge.opponent,
                        prop_type=edge.prop_type,
                        prop_label=edge.prop_label,
                        best_over_line=edge.best_over_line,
                        best_over_odds=edge.best_over_odds,
                        best_over_book=edge.best_over_book,
                        best_under_line=edge.best_under_line,
                        best_under_odds=edge.best_under_odds,
                        best_under_book=edge.best_under_book,
                        line_spread=edge.line_spread,
                        all_lines=edge.all_lines,
                        player_avg=edge.player_avg,
                        edge_direction=edge.edge_direction,
                        edge_strength=edge.edge_strength,
                        edge_reason=edge.edge_reason,
                        web_context=edge.web_context,
                        is_best_bet=is_best,
                        generated_at=datetime.utcnow(),
                    )
                    db.add(db_edge)
                    saved += 1

                db.commit()
                logger.info(f"[Scheduler] ✅ {sport}: {saved} prop edges saved.")

            except Exception as e:
                logger.error(f"[Scheduler] Props failed for {sport}: {e}")
                db.rollback()

        db.close()
    except Exception as e:
        logger.error(f"[Scheduler] Props job failed: {e}")


def job_ai_news_analysis():
    """
    Run AI analysis on latest news. Runs every 3 hours.
    Saves analysis results to database for dashboard display.
    """
    logger.info("[Scheduler] 🤖 Running AI news analysis...")
    try:
        from analysis.news_analyzer import NewsAnalyzer
        from database.models import get_session, NewsArticle
        analyzer = NewsAnalyzer()

        db = get_session()
        try:
            # Get sports that have recent news
            sports = [s[0] for s in db.query(NewsArticle.sport).distinct().all()]
        finally:
            db.close()

        for sport in sports:
            try:
                result = analyzer.analyze_news_for_sport(sport)
                # Store in a simple file for dashboard to read
                import os
                os.makedirs("analysis_cache", exist_ok=True)
                with open(f"analysis_cache/{sport}_analysis.txt", "w") as f:
                    f.write(result)
                logger.info(f"[Scheduler] ✅ {sport} AI analysis complete.")
            except Exception as e:
                logger.error(f"[Scheduler] AI analysis failed for {sport}: {e}")

    except Exception as e:
        logger.error(f"[Scheduler] AI news job failed: {e}")


def job_update_gamelogs():
    """
    Backfill/refresh player game logs from MLB Stats API.
    Runs once daily — keeps hit rates and projections current.
    """
    logger.info("[Scheduler] 📊 Updating player game logs...")
    try:
        from data_ingestion.official.mlb_gamelog import MLBGameLogBackfill
        backfill = MLBGameLogBackfill()
        try:
            backfill.run_backfill()
        finally:
            backfill.close()
    except Exception as e:
        logger.error(f"[Scheduler] Game log update failed: {e}")


def job_update_contracts():
    """Update contract data. Runs once per day."""
    from data_ingestion.contracts.contract_client import ContractClient
    logger.info("[Scheduler] 💰 Updating contracts...")
    client = ContractClient()
    client.run_all_sports()


def job_full_daily_refresh():
    """Full refresh including ESPN teams/rosters. Runs at 7am daily."""
    from data_ingestion.official.espn_client import ESPNClient
    logger.info("[Scheduler] 🔄 Running full daily refresh...")
    client = ESPNClient()
    client.run_all_sports()


def run_initial_load():
    """Run everything once on startup."""
    logger.info("=" * 60)
    logger.info("🚀 Running initial data load...")
    logger.info("=" * 60)

    logger.info("Step 1/6: Loading schedules from OddsAPI...")
    try:
        from data_ingestion.official.schedule_engine import ScheduleEngine
        engine = ScheduleEngine()
        engine.run_full_schedule_load()
    except Exception as e:
        logger.error(f"Schedule load failed: {e}")

    logger.info("Step 2/6: Loading odds...")
    try:
        from data_ingestion.official.odds_client import OddsClient
        odds = OddsClient()
        odds.run_all_sports()
    except Exception as e:
        logger.error(f"Odds load failed: {e}")

    logger.info("Step 3/6: Loading news...")
    try:
        from data_ingestion.soft.news_client import NewsClient
        news = NewsClient()
        news.run_all_sports()
    except Exception as e:
        logger.error(f"News load failed: {e}")

    logger.info("Step 4/6: Loading ESPN teams/injuries...")
    try:
        from data_ingestion.official.espn_client import ESPNClient
        espn = ESPNClient()
        espn.run_all_sports()
    except Exception as e:
        logger.error(f"ESPN load failed: {e}")

    logger.info("Step 5/6: Fetching player props...")
    try:
        job_update_props()
    except Exception as e:
        logger.error(f"Props load failed: {e}")

    logger.info("Step 6/6: Running AI news analysis...")
    try:
        job_ai_news_analysis()
    except Exception as e:
        logger.error(f"AI analysis failed: {e}")

    logger.info("✅ Initial load complete. Scheduler running.")


def main():
    logger.info("=" * 60)
    logger.info("  SPORTS BETTING BOT — SCHEDULER")
    logger.info(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    run_initial_load()

    scheduler = BlockingScheduler(timezone="America/New_York")

    scheduler.add_job(
        job_update_schedule, IntervalTrigger(hours=3),
        id="schedule", name="Game Schedule", max_instances=1
    )
    scheduler.add_job(
        job_update_odds, IntervalTrigger(hours=2),
        id="odds", name="Live Odds", max_instances=1
    )
    scheduler.add_job(
        job_update_news, IntervalTrigger(minutes=30),
        id="news", name="News Feed", max_instances=1
    )
    scheduler.add_job(
        job_update_injuries, IntervalTrigger(hours=2),
        id="injuries", name="Injury Reports", max_instances=1
    )
    scheduler.add_job(
        job_update_props, IntervalTrigger(hours=6),
        id="props", name="Player Props", max_instances=1
    )
    scheduler.add_job(
        job_ai_news_analysis, IntervalTrigger(hours=4),
        id="ai_analysis", name="AI News Analysis", max_instances=1
    )
    scheduler.add_job(
        job_update_contracts, CronTrigger(hour=6, minute=0),
        id="contracts", name="Contracts", max_instances=1
    )
    scheduler.add_job(
        job_update_gamelogs, CronTrigger(hour=5, minute=0),
        id="gamelogs", name="Player Game Logs", max_instances=1
    )
    scheduler.add_job(
        job_full_daily_refresh, CronTrigger(hour=7, minute=0),
        id="daily_refresh", name="Daily Refresh", max_instances=1
    )

    logger.info("✅ All jobs scheduled:")
    for job in scheduler.get_jobs():
        logger.info(f"   [{job.name}] → {job.trigger}")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("🛑 Scheduler stopped.")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
