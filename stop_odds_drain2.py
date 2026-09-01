"""
Safer approach: add an early-return guard inside the two credit-spending
job functions so they do nothing when called. Can't break indentation
because we insert a properly-indented line right after the def/docstring.
"""
import re

path = "scheduler/scheduler.py"
src = open(path, encoding="utf-8").read()
orig = src

GUARD = '    return  # [DISABLED to save OddsAPI credits - fetch props manually in Value tab]\n'

def add_guard(src, job_name):
    # Find the function definition line
    def_pattern = re.compile(r'(def ' + job_name + r'\([^)]*\):\n)')
    m = def_pattern.search(src)
    if not m:
        return src, "not found"
    insert_pos = m.end()

    # If there's a docstring right after, insert AFTER it
    rest = src[insert_pos:]
    doc_match = re.match(r'(\s*"""[\s\S]*?"""\n)', rest)
    if doc_match:
        insert_pos += doc_match.end()

    # Check not already guarded
    after = src[insert_pos:insert_pos+120]
    if "DISABLED to save OddsAPI" in after:
        return src, "already disabled"

    new_src = src[:insert_pos] + GUARD + src[insert_pos:]
    return new_src, "disabled"

for job in ["job_update_odds", "job_update_props"]:
    src, status = add_guard(src, job)
    print(f"{status}: {job}")

if src != orig:
    open(path + ".backup2", "w", encoding="utf-8").write(orig)
    open(path, "w", encoding="utf-8").write(src)
    print("Saved. Backup: scheduler/scheduler.py.backup2")

import ast
try:
    ast.parse(open(path, encoding="utf-8").read())
    print("✓ scheduler.py parses cleanly")
except SyntaxError as e:
    print(f"✗ SYNTAX ERROR: {e}")
    open(path, "w", encoding="utf-8").write(orig)
    print("Restored original — tell Claude.")
