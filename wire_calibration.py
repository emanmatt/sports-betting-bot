"""
Wire auto-calibration into the prop ranker.
Adds: load calibration once in rank_all_props, apply multiplier to each
prop's score. UTF-8 safe, backs up first, auto-restores on error.
"""
import re

path = "analysis/prop_ranker.py"
src = open(path, encoding="utf-8").read()
orig = src

# 1. Load calibration at the start of rank_all_props (after props = [])
# Find "props = []" inside rank_all_props
if "self._calibration = None" not in src:
    # Add calibration load right after the lazy-load helpers section.
    # We anchor on the BvP loader we know exists.
    anchor = "        try:\n            from analysis.bvp_matchup import BvPMatchup"
    if anchor in src:
        inject = (
            "        # Auto-calibration from track record (learns from past results)\n"
            "        try:\n"
            "            from analysis.auto_calibration import AutoCalibration\n"
            "            self._calibration = AutoCalibration().load()\n"
            "        except Exception:\n"
            "            self._calibration = None\n\n"
        )
        src = src.replace(anchor, inject + anchor, 1)
        print("[1] calibration loader injected")
    else:
        print("[1] WARNING: anchor not found — check manually")
else:
    print("[1] calibration already wired")

# 2. Apply the multiplier at the end of _score, right before the return.
# The score function ends with: return max(0, min(100, round(score, 1)))
score_return = "        return max(0, min(100, round(score, 1)))"
if score_return in src and "calibration multiplier" not in src:
    apply_calib = (
        "        # Apply auto-calibration multiplier (learned from track record).\n"
        "        # Muted by sample size + capped ±15%, so it nudges, never dominates.\n"
        "        calib = getattr(self, '_calibration', None)\n"
        "        if calib is not None:\n"
        "            m = calib.prop_multiplier(pr.prop_label)\n"
        "            m *= calib.tier_multiplier(pr.tier)\n"
        "            score *= m  # calibration multiplier\n\n"
        + score_return
    )
    src = src.replace(score_return, apply_calib, 1)
    print("[2] calibration multiplier applied in _score")
else:
    if "calibration multiplier" in src:
        print("[2] multiplier already applied")
    else:
        print("[2] WARNING: score return line not found — check manually")

if src != orig:
    open(path + ".precalib", "w", encoding="utf-8").write(orig)
    open(path, "w", encoding="utf-8").write(src)
    print("Saved. Backup: analysis/prop_ranker.py.precalib")

import ast
try:
    ast.parse(open(path, encoding="utf-8").read())
    print("✓ prop_ranker.py parses cleanly")
except SyntaxError as e:
    print(f"✗ SYNTAX ERROR: {e}")
    open(path, "w", encoding="utf-8").write(orig)
    print("Restored original — tell Claude.")
