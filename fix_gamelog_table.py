"""
One-time fix: drops BOTH foreign key constraints on player_stats
so game logs save independently of games/players tables.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from database.models import get_engine

engine = get_engine()

statements = [
    "ALTER TABLE player_stats DROP CONSTRAINT IF EXISTS player_stats_game_id_fkey;",
    "ALTER TABLE player_stats DROP CONSTRAINT IF EXISTS player_stats_player_id_fkey;",
    "ALTER TABLE player_stats ADD COLUMN IF NOT EXISTS rbi INTEGER;",
    "ALTER TABLE player_stats ADD COLUMN IF NOT EXISTS total_bases INTEGER;",
]

with engine.connect() as conn:
    for stmt in statements:
        try:
            conn.execute(text(stmt))
            conn.commit()
            print(f"OK: {stmt[:60]}")
        except Exception as e:
            print(f"Note ({stmt[:40]}...): {e}")

print("\nDone! Foreign keys dropped. Now run: python load_gamelogs.py")
