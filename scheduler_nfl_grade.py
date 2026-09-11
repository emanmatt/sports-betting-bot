"""
Add NFL grading to the daily scheduler grade job, so NFL grades once
a day on Railway (backup to the on-rank grading). Exact-match, backs up.
"""
import ast

path = "scheduler/scheduler.py"
src = open(path, encoding="utf-8").read()
orig = src

old = '''        tr = TrackRecord()
        try:
            graded = tr.grade_pending()
            logger.info(f"[Scheduler] Graded {graded} predictions.")
        finally:
            tr.close()
    except Exception as e:
        logger.error(f"[Scheduler] Prediction grading failed: {e}")'''

new = '''        tr = TrackRecord()
        try:
            graded = tr.grade_pending()
            logger.info(f"[Scheduler] Graded {graded} MLB predictions.")
        finally:
            tr.close()
    except Exception as e:
        logger.error(f"[Scheduler] MLB grading failed: {e}")

    # NFL grading (own grader — pulls Week N results from ESPN)
    try:
        from analysis.nfl_grader import NFLGrader
        n = NFLGrader().grade_pending()
        logger.info(f"[Scheduler] Graded {n} NFL predictions.")
    except Exception as e:
        logger.error(f"[Scheduler] NFL grading failed: {e}")'''

if old in src:
    src = src.replace(old, new, 1)
    print("[1] NFL grading added to daily scheduler job")
else:
    print("[1] grade job block not matched")

if src != orig:
    open(path + ".prenflgrade", "w", encoding="utf-8").write(orig)
    open(path, "w", encoding="utf-8").write(src)

try:
    ast.parse(open(path, encoding="utf-8").read())
    print("\u2713 scheduler.py parses cleanly")
except SyntaxError as e:
    print(f"\u2717 SYNTAX ERROR: {e}")
    open(path, "w", encoding="utf-8").write(orig)
    print("  restored")
