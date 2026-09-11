"""Show the scheduler's grade job so we add NFL grading to it."""
sch = open("scheduler/scheduler.py", encoding="utf-8").read()
import re
m = re.search(r'def job_grade_predictions\(\):.*?(?=\ndef )', sch, re.DOTALL)
if m:
    print(m.group(0))
else:
    print("job_grade_predictions not found")
