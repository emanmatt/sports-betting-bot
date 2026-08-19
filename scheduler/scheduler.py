"""
scheduler/scheduler.py
Runs all data pipelines automatically on schedule.
Start with: python scheduler/scheduler.py

Schedule:
  - Odds:     every 5 min
  - Injuries: every 15 min
  - News RSS: every 30 min
  - Reddit:   every 60 min
  - Stats:    every 2 hours
  - Contracts: once per day at 6am
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from datetime import datetime
from config.settings import SCHEDULE_INTERVALS, SUPPORTED_SPORTS


def job_update_odds():
    """Update live odds for all sports. Runs every 5 min."""
    from data_ingestion.official.odds_client import OddsClient
    logger.info("[Scheduler] ⚡ Running odds update...")
    client = OddsClient()
    client.run_all_sports()


def job_update_injuries():
    """Pull latest injury reports. Runs every 15 min."""
    from data_ingestion.official.espn_client import ESPNClient
    logger.info("[Scheduler] 🏥 Running injury update...")
    client = ESPNClient()
    for sport in SUPPORTED_SPORTS:
        client.save_injuries(sport)


def job_update_news():
    """Pull RSS news feeds. Runs every 30 min."""
    from data_ingestion.soft.news_client import NewsClient
    logger.info("[Scheduler] 📰 Running news update...")
    client = NewsClient()
    client.run_all_sports()


def job_update_reddit():
    """Scrape Reddit for rumors and news. Runs every 60 min."""
    from data_ingestion.soft.reddit_client import RedditClient
    logger.info("[Scheduler] 🤖 Running Reddit scrape...")
    client = RedditClient()
    client.run_all_sports()


def job_update_schedule():
    """Update game schedules and scores. Runs every 2 hours."""
    from data_ingestion.official.espn_client import ESPNClient
    logger.info("[Scheduler] 📅 Running schedule update...")
    client = ESPNClient()
    for sport in SUPPORTED_SPORTS:
        client.save_schedule(sport)


def job_update_contracts():
    """Update contract data. Runs once per day."""
    from data_ingestion.contracts.contract_client import ContractClient
    logger.info("[Scheduler] 💰 Running contract update...")
    client = ContractClient()
    client.run_all_sports()


def job_full_daily_refresh():
    """Full data refresh including all rosters. Runs at 6am daily."""
    from data_ingestion.official.espn_client import ESPNClient
    logger.info("[Scheduler] 🔄 Running full daily refresh...")
    client = ESPNClient()
    client.run_all_sports()


def run_initial_load():
    """Run everything once on startup to populate the database."""
    logger.info("=" * 60)
    logger.info("🚀 Running initial data load...")
    logger.info("=" * 60)

    logger.info("Step 1/5: Loading teams and players from ESPN...")
    from data_ingestion.official.espn_client import ESPNClient
    espn = ESPNClient()
    espn.run_all_sports()

    logger.info("Step 2/5: Loading current odds...")
    from data_ingestion.official.odds_client import OddsClient
    odds = OddsClient()
    odds.run_all_sports()

    logger.info("Step 3/5: Loading news feeds...")
    from data_ingestion.soft.news_client import NewsClient
    news = NewsClient()
    news.run_all_sports()

    logger.info("Step 4/5: Loading Reddit data...")
    from data_ingestion.soft.reddit_client import RedditClient
    reddit = RedditClient()
    reddit.run_all_sports()

    logger.info("Step 5/5: Loading contract data...")
    from data_ingestion.contracts.contract_client import ContractClient
    contracts = ContractClient()
    contracts.run_all_sports()

    logger.info("✅ Initial data load complete! Scheduler now running.")


def main():
    logger.info("=" * 60)
    logger.info("  SPORTS BETTING BOT — DATA SCHEDULER")
    logger.info(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Run initial load to populate DB
    run_initial_load()

    # Set up scheduler
    scheduler = BlockingScheduler(timezone="America/New_York")

    scheduler.add_job(
        job_update_odds, IntervalTrigger(minutes=5),
        id="odds", name="Live Odds Update", max_instances=1
    )
    scheduler.add_job(
        job_update_injuries, IntervalTrigger(minutes=15),
        id="injuries", name="Injury Report Update", max_instances=1
    )
    scheduler.add_job(
        job_update_news, IntervalTrigger(minutes=30),
        id="news", name="RSS News Feed", max_instances=1
    )
    scheduler.add_job(
        job_update_reddit, IntervalTrigger(minutes=60),
        id="reddit", name="Reddit Scraper", max_instances=1
    )
    scheduler.add_job(
        job_update_schedule, IntervalTrigger(hours=2),
        id="schedule", name="Game Schedule Update", max_instances=1
    )
    scheduler.add_job(
        job_update_contracts, CronTrigger(hour=6, minute=0),
        id="contracts", name="Daily Contract Update", max_instances=1
    )
    scheduler.add_job(
        job_full_daily_refresh, CronTrigger(hour=6, minute=30),
        id="daily_refresh", name="Full Daily Roster Refresh", max_instances=1
    )

    logger.info("✅ All jobs scheduled. Bot is now running 24/7.")
    logger.info("   Press Ctrl+C to stop.")

    jobs = scheduler.get_jobs()
    for job in jobs:
        logger.info(f"   [{job.name}] → {job.trigger}")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("\n🛑 Scheduler stopped by user.")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
