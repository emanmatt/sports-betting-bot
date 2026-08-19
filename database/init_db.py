"""
database/init_db.py
Run this ONCE to create all tables in your PostgreSQL database.

Usage:
    python database/init_db.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from database.models import create_all_tables, get_engine
from config.settings import DATABASE_URL


def init():
    logger.info("Connecting to database...")
    logger.info(f"URL: {DATABASE_URL.split('@')[-1]}")  # Log host only, not credentials

    try:
        engine = get_engine()
        # Test connection
        with engine.connect() as conn:
            logger.info("✅ Database connection successful.")

        # Create all tables
        create_all_tables()
        logger.info("✅ Database initialized. Ready to collect data.")

    except Exception as e:
        logger.error(f"❌ Database init failed: {e}")
        logger.info("Make sure PostgreSQL is running and your DATABASE_URL in .env is correct.")
        logger.info("Quick fix: install PostgreSQL, then run:")
        logger.info("  createdb sportsbetting")
        raise


if __name__ == "__main__":
    init()
