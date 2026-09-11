"""Show the full get_stats method so Claude patches the sport filter properly."""
tr = open("analysis/track_record.py", encoding="utf-8").read()
import re
m = re.search(r'    def get_stats\(self.*?(?=\n    def )', tr, re.DOTALL)
if m:
    print(m.group(0))
else:
    print("get_stats not found in expected form")
