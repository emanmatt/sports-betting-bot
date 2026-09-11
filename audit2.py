"""
Deep audit: WHY is the score inverted? Cross-tab score vs prop type
vs outcome to find where high scores are going wrong.
"""
import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database.models import get_engine

engine = get_engine()
print("="*64)
print("  WHY IS THE SCORE INVERTED? — root cause hunt")
print("="*64)

with engine.connect() as conn:
    # 1. What prop types live in the HIGH score bucket vs LOW?
    print("\n--- What's IN each score bucket? (prop mix by score) ---")
    for lo, hi, lbl in [(70,101,"HIGH 70+"),(60,70,"MID 60-70"),(50,60,"LOW 50-60")]:
        print(f"\n  {lbl}:")
        rows = conn.execute(text("""
            SELECT prop_label, COUNT(*),
                   SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)
            FROM predictions WHERE graded=TRUE AND score>=:lo AND score<:hi
            GROUP BY prop_label ORDER BY COUNT(*) DESC LIMIT 6
        """), {"lo":lo,"hi":hi}).fetchall()
        for label, n, h in rows:
            h = h or 0
            print(f"     {label:22} {n:3} bets, {h/n*100:.0f}% hit")

    # 2. Within JUST 1+ Hits (the good prop), does score predict?
    print("\n--- Within '1+ Hits' ONLY: does score predict hits? ---")
    print("    (isolates the score from prop-type noise)")
    for lo, hi in [(70,101),(60,70),(50,60),(0,50)]:
        row = conn.execute(text("""
            SELECT COUNT(*), SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)
            FROM predictions WHERE graded=TRUE AND prop_label='1+ Hits'
              AND score>=:lo AND score<:hi
        """), {"lo":lo,"hi":hi}).first()
        n, h = row[0], row[1] or 0
        if n:
            print(f"     score {lo}-{hi}: {h}/{n} = {h/n*100:.0f}%")

    # 3. Does the raw L10 rate predict better than the final score?
    print("\n--- Does raw L10 hit-rate predict better than the SCORE? ---")
    print("    (if yes, the fancy factors are HURTING)")
    for lo, hi in [(80,101),(70,80),(60,70),(0,60)]:
        row = conn.execute(text("""
            SELECT COUNT(*), SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)
            FROM predictions WHERE graded=TRUE AND l10_rate>=:lo AND l10_rate<:hi
        """), {"lo":lo,"hi":hi}).first()
        n, h = row[0], row[1] or 0
        if n:
            print(f"     L10 {lo}-{hi}%: {h}/{n} = {h/n*100:.0f}%")

    # 4. Pitcher vs batter split
    print("\n--- Pitcher vs Batter ---")
    for isp, lbl in [(True,"Pitcher"),(False,"Batter")]:
        row = conn.execute(text("""
            SELECT COUNT(*), SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END)
            FROM predictions WHERE graded=TRUE AND is_pitcher=:p
        """), {"p":isp}).first()
        n, h = row[0], row[1] or 0
        if n:
            print(f"     {lbl}: {h}/{n} = {h/n*100:.0f}%")
