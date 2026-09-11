"""
Add a 'sport' column to the predictions table so MLB and NFL stay
separate. Safe: adds column if missing, backfills existing rows as MLB
(all 394 current predictions are MLB), does NOT touch any other data.
"""
import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database.models import get_engine

engine = get_engine()

with engine.connect() as conn:
    # 1. Does the column exist?
    col_exists = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='predictions' AND column_name='sport'
    """)).first()

    if col_exists:
        print("sport column already exists — skipping add")
    else:
        conn.execute(text("ALTER TABLE predictions ADD COLUMN sport VARCHAR(10)"))
        conn.commit()
        print("✓ added 'sport' column")

    # 2. Backfill any NULL sport as MLB (all existing predictions are MLB)
    updated = conn.execute(text("""
        UPDATE predictions SET sport='MLB' WHERE sport IS NULL
    """))
    conn.commit()
    print(f"✓ backfilled existing rows as MLB")

    # 3. Verify
    total = conn.execute(text("SELECT COUNT(*) FROM predictions")).scalar()
    mlb = conn.execute(text("SELECT COUNT(*) FROM predictions WHERE sport='MLB'")).scalar()
    print(f"\nTotal predictions: {total} | tagged MLB: {mlb}")
    print("Your existing MLB track record is preserved and tagged.")
