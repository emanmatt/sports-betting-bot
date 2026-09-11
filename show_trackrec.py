"""Show how track_record logs + how the NFL tab could feed it."""
tr = open("analysis/track_record.py", encoding="utf-8").read()
import re
print("=== track_record: log_predictions signature + what it reads from props ===")
m = re.search(r'def log_predictions\(self.*?(?=\n    def )', tr, re.DOTALL)
if m:
    print(m.group(0)[:1400])
