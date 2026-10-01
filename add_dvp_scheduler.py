"""
add_dvp_scheduler.py — adds a weekly Defense-vs-Position refresh job to
scheduler/scheduler.py (Tuesdays 8am ET, free/ESPN-only). Backs up first.
Run once:  python add_dvp_scheduler.py   then commit + push.
"""
import io
import shutil

PATH = "scheduler/scheduler.py"

FUNC = '''
def job_refresh_dvp():
    """Rebuild Defense-vs-Position ranks (ESPN only, free). Runs weekly."""
    logger.info("[Scheduler] \\U0001F6E1\\uFE0F Refreshing Defense-vs-Position...")
    try:
        from analysis.nfl_ranker import NFLRanker
        from analysis.dvp_engine import refresh_dvp
        blob = refresh_dvp(NFLRanker().nfl)
        logger.info(f"[Scheduler] DvP refreshed: {blob.get('n_teams')} defenses.")
    except Exception as e:
        logger.error(f"[Scheduler] DvP refresh failed: {e}")


'''

JOB = '''    scheduler.add_job(
        job_refresh_dvp, CronTrigger(day_of_week="tue", hour=8, minute=0),
        id="dvp", name="Defense vs Position", max_instances=1
    )
'''

def main():
    txt = io.open(PATH, encoding="utf-8").read()
    if "job_refresh_dvp" in txt:
        print("Already added — nothing to do.")
        return
    shutil.copy(PATH, PATH + ".bak")
    print(f"backed up {PATH} -> {PATH}.bak")

    # 1) insert the function right before run_initial_load
    anchor_fn = "def run_initial_load():"
    if anchor_fn not in txt:
        print("!! couldn't find run_initial_load — aborting, no changes made.")
        return
    txt = txt.replace(anchor_fn, FUNC.lstrip("\n") + "\n" + anchor_fn, 1)

    # 2) register the job right after the daily_refresh add_job block
    anchor_job = ('        id="daily_refresh", name="Daily Refresh", '
                  'max_instances=1\n    )\n')
    if anchor_job not in txt:
        print("!! couldn't find daily_refresh job block — aborting.")
        return
    txt = txt.replace(anchor_job, anchor_job + JOB, 1)

    io.open(PATH, "w", encoding="utf-8").write(txt)
    print(f"wrote {PATH}")

    import ast
    try:
        ast.parse(txt)
        print("OK — scheduler.py parses. Weekly DvP refresh scheduled (Tue 8am ET).")
    except SyntaxError as e:
        print("!! SYNTAX ERROR:", e, "— restore from .bak")

if __name__ == "__main__":
    main()
