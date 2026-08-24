"""Verify each stage of the learning loop is working."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from database.models import get_engine
from analysis.track_record import ensure_predictions_table, TrackRecord

ensure_predictions_table()
engine = get_engine()

print("=" * 55)
print("  LEARNING LOOP HEALTH CHECK")
print("=" * 55)

with engine.connect() as conn:
    # Stage 1: predictions logged
    total = conn.execute(text("SELECT COUNT(*) FROM predictions")).scalar()
    print(f"\n[1] PREDICTIONS LOGGED: {total}")
    if total == 0:
        print("    ❌ None yet — rank a board in Top Props to log some")
    else:
        print("    ✅ Logging works")

    # Show a few
    rows = conn.execute(text("""
        SELECT pred_date, player_name, prop_label, tier, score, graded, result
        FROM predictions ORDER BY created_at DESC LIMIT 5
    """)).fetchall()
    print("\n    Most recent predictions:")
    for r in rows:
        g = "graded" if r[5] else "pending"
        res = r[6] or "-"
        print(f"      {r[0]} | {r[1]} {r[2]} | Tier {r[3]} | {g} | {res}")

    # Stage 2: graded
    graded = conn.execute(text("SELECT COUNT(*) FROM predictions WHERE graded=TRUE")).scalar()
    pending = conn.execute(text("SELECT COUNT(*) FROM predictions WHERE graded=FALSE")).scalar()
    print(f"\n[2] GRADED: {graded} | PENDING: {pending}")
    if graded == 0 and pending > 0:
        print("    ⏳ Predictions waiting to be graded")
        print("    → They grade once the game date has passed AND game logs updated")
        print("    → Run: python -c \"from analysis.track_record import TrackRecord; t=TrackRecord(); print(t.grade_pending()); t.close()\"")
    elif graded > 0:
        print("    ✅ Grading works")

# Stage 3: stats
tr = TrackRecord()
stats = tr.get_stats()
print(f"\n[3] STATS/CALIBRATION:")
if stats.get("total", 0) == 0:
    print("    ⏳ No graded predictions yet — needs games to finish + grading")
else:
    print(f"    ✅ Overall hit rate: {stats['overall_rate']}% ({stats['total']} graded)")
    for tier, d in stats.get("by_tier", {}).items():
        print(f"       Tier {tier}: {d['rate']}%")
tr.close()

print("\n[4] CLAUDE REVIEW: available in Track Record tab once stats exist")
print("=" * 55)
