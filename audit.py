"""
Self-audit: pull real performance data so we can see what's actually
wrong, not guess. Reads the track record and reports honestly.
"""
import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database.models import get_engine

engine = get_engine()
print("="*60)
print("  PERFORMANCE AUDIT — real numbers, no guessing")
print("="*60)

with engine.connect() as conn:
    # Overall
    total = conn.execute(text("SELECT COUNT(*) FROM predictions")).scalar()
    graded = conn.execute(text("SELECT COUNT(*) FROM predictions WHERE graded=TRUE")).scalar()
    hits = conn.execute(text("SELECT COUNT(*) FROM predictions WHERE result='hit'")).scalar()
    print(f"\nTotal predictions: {total} | graded: {graded} | pending: {total-graded}")
    if graded:
        print(f"Overall hit rate: {hits}/{graded} = {hits/graded*100:.1f}%")

    if graded < 10:
        print("\n⚠️ Fewer than 10 graded — too small to conclude much yet.")
        print("   The 'not hitting' feeling may be small-sample variance.")

    # By tier — is the tier system meaningful?
    print("\n--- BY TIER (are A plays actually better than B/C?) ---")
    for tier in ['A','B','C']:
        row = conn.execute(text("""
            SELECT COUNT(*), SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)
            FROM predictions WHERE graded=TRUE AND tier=:t
        """), {"t": tier}).first()
        n, h = row[0], row[1] or 0
        if n:
            print(f"  Tier {tier}: {h}/{n} = {h/n*100:.0f}%")

    # By prop type — which props hit and which don't?
    print("\n--- BY PROP TYPE (what to trust vs fade) ---")
    rows = conn.execute(text("""
        SELECT prop_label, COUNT(*), SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)
        FROM predictions WHERE graded=TRUE
        GROUP BY prop_label HAVING COUNT(*) >= 3
        ORDER BY 3.0*SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)/COUNT(*) DESC
    """)).fetchall()
    for label, n, h in rows:
        h = h or 0
        print(f"  {label:24} {h}/{n} = {h/n*100:.0f}%")

    # Does model score correlate with hits? (is the score meaningful?)
    print("\n--- SCORE CALIBRATION (does higher score = more hits?) ---")
    for lo, hi in [(70,101),(60,70),(50,60),(0,50)]:
        row = conn.execute(text("""
            SELECT COUNT(*), SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)
            FROM predictions WHERE graded=TRUE AND score>=:lo AND score<:hi
        """), {"lo": lo, "hi": hi}).first()
        n, h = row[0], row[1] or 0
        if n:
            print(f"  Score {lo}-{hi}: {h}/{n} = {h/n*100:.0f}%")

    # Recent trend — getting better or worse?
    print("\n--- BY DATE (recent form of the model itself) ---")
    rows = conn.execute(text("""
        SELECT pred_date, COUNT(*), SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)
        FROM predictions WHERE graded=TRUE
        GROUP BY pred_date ORDER BY pred_date DESC LIMIT 7
    """)).fetchall()
    for d, n, h in rows:
        h = h or 0
        print(f"  {d}: {h}/{n} = {h/n*100:.0f}%")

print("\n" + "="*60)
print("Paste this whole output to Claude for the real audit.")
