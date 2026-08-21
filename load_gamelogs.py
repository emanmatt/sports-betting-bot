"""Run this once to backfill player game logs for hit rates + projections."""
from data_ingestion.official.mlb_gamelog import MLBGameLogBackfill

backfill = MLBGameLogBackfill()
try:
    total = backfill.run_backfill()
    print(f"\nDone! {total} game logs saved to database.")
    print("Hit rates and projections will now work in the dashboard.")
finally:
    backfill.close()
