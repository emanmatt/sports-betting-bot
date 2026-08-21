"""
Clean rebuild of game logs:
1. Wipes the orphaned game-log rows (no names, empty hits column)
2. Re-runs backfill with the FIXED code that stores names + hits properly

This fixes the "0 batters ranked" problem.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from database.models import get_engine, get_session, PlayerStats
from data_ingestion.official.mlb_gamelog import MLBGameLogBackfill

print("Step 1: Wiping orphaned game-log rows...")
db = get_session()
try:
    # Delete all MLBLOG_ prefixed stats (the orphaned backfill rows)
    deleted = db.query(PlayerStats).filter(
        PlayerStats.game_id.like("MLBLOG_%")
    ).delete(synchronize_session=False)
    db.commit()
    print(f"  Deleted {deleted} orphaned rows.")
except Exception as e:
    db.rollback()
    print(f"  Error: {e}")
finally:
    db.close()

print("\nStep 2: Re-running backfill with fixed code (names + hits)...")
backfill = MLBGameLogBackfill()
try:
    total = backfill.run_backfill()
    print(f"\nDone! {total} game logs rebuilt WITH names and hits.")
    print("Now the Top Hits ranker will work.")
finally:
    backfill.close()
