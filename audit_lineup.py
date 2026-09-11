"""
Check if lineup/bench issues are causing misses.
A player who didn't play shows near-zero actual value. If lots of
misses have actual_value ~0, they likely SAT (not model failure).
"""
import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database.models import get_engine

engine = get_engine()
print("="*60)
print("  LINEUP / BENCH IMPACT ON MISSES")
print("="*60)

with engine.connect() as conn:
    # For batter hit props that MISSED, how many had actual_value = 0?
    # (0 hits could mean played-and-went-hitless OR didn't play)
    total_miss = conn.execute(text("""
        SELECT COUNT(*) FROM predictions
        WHERE graded=TRUE AND result='miss' AND is_pitcher=FALSE
    """)).scalar()

    zero_miss = conn.execute(text("""
        SELECT COUNT(*) FROM predictions
        WHERE graded=TRUE AND result='miss' AND is_pitcher=FALSE
          AND (actual_value = 0 OR actual_value IS NULL)
    """)).scalar()

    print(f"\nBatter misses: {total_miss}")
    print(f"  of those with actual_value 0 or null: {zero_miss}")
    if total_miss:
        print(f"  = {zero_miss/total_miss*100:.0f}% of misses were total zeros")
        print("  (a chunk of these may be players who didn't start / barely played)")

    # Null actual_value = we couldn't even grade it properly
    null_actual = conn.execute(text("""
        SELECT COUNT(*) FROM predictions
        WHERE graded=TRUE AND actual_value IS NULL
    """)).scalar()
    print(f"\nGraded but actual_value is NULL: {null_actual}")
    print("  (these graded as miss by default — possible data/lineup gaps)")

    # Distribution of actual values on hits props
    print("\n--- actual_value distribution on 1+ Hits bets ---")
    rows = conn.execute(text("""
        SELECT actual_value, COUNT(*),
               SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)
        FROM predictions WHERE graded=TRUE AND prop_label='1+ Hits'
        GROUP BY actual_value ORDER BY actual_value
    """)).fetchall()
    for av, n, h in rows:
        print(f"     {av} hits: {n} bets ({h or 0} graded hit)")
