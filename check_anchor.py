"""Verify the exact 'side' param text so the patch anchor matches."""
tr = open("analysis/track_record.py", encoding="utf-8").read()
import re
# find the params dict in log_predictions — the "side": ... line
for ln in tr.split("\n"):
    if '"side"' in ln:
        print(f"side param line: {repr(ln.strip())}")
