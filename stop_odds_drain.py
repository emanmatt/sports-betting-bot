"""
Stop the automatic OddsAPI credit drain.
Disables job_update_odds (every 30min) and job_update_props (every 2hr)
so credits are only spent when YOU manually fetch props in the Value tab.
Keeps all free MLB jobs (gamelogs, grading, schedule, injuries) running.
"""
import re

path = "scheduler/scheduler.py"
src = open(path, encoding="utf-8").read()
orig = src

# Comment out the add_job calls for the two credit-spending jobs.
# We match the whole scheduler.add_job(...) block for each.
def disable_job(src, job_name):
    # Find "scheduler.add_job(\n job_name, ... )" including multiline
    pattern = re.compile(
        r'(scheduler\.add_job\(\s*' + job_name + r'\b.*?\))',
        re.DOTALL
    )
    m = pattern.search(src)
    if not m:
        return src, False
    block = m.group(1)
    if block.lstrip().startswith("#"):
        return src, False  # already disabled
    # Comment out every line of the block
    commented = "\n".join("# " + ln if ln.strip() else ln
                          for ln in block.split("\n"))
    commented = "# [DISABLED to save OddsAPI credits — fetch props manually in Value tab]\n" + commented
    return src.replace(block, commented), True

for job in ["job_update_odds", "job_update_props"]:
    src, changed = disable_job(src, job)
    print(f"{'✓ disabled' if changed else '– already off / not found'}: {job}")

if src != orig:
    # backup first
    open(path + ".backup", "w", encoding="utf-8").write(orig)
    open(path, "w", encoding="utf-8").write(src)
    print("Saved. Backup written to scheduler/scheduler.py.backup")
else:
    print("No changes made.")

# verify it still parses
import ast
try:
    ast.parse(open(path, encoding="utf-8").read())
    print("✓ scheduler.py parses cleanly")
except SyntaxError as e:
    print(f"✗ SYNTAX ERROR: {e}")
    print("Restoring backup...")
    if src != orig:
        open(path, "w", encoding="utf-8").write(orig)
        print("Restored original. Tell Claude — we'll fix it differently.")
