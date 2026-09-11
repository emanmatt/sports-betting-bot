"""Check which fixes are actually applied in the current files."""
pr = open("analysis/prop_ranker.py", encoding="utf-8").read()
tab = open("dashboard/tophits_tab.py", encoding="utf-8").read()

print("=== CURRENT STATE OF FIXES ===\n")
print("CONFIRMED-LINEUP FIX:")
print(f"  ranker skip logic:  {'✓ applied' if 'confirmed_only and not game.get' in pr else '✗ NOT applied'}")
print(f"  tab toggle:         {'✓ applied' if 'confirmed_only_toggle' in tab else '✗ NOT applied'}")

print("\nLEAN SCORING FIX:")
print(f"  lean _score:        {'✓ applied' if 'LEAN score' in pr else '✗ NOT applied'}")

print("\nSTALE MESSAGES:")
proj_msg = "showing projected batters from the active" in tab
print(f"  old projected msg present: {'yes — needs fix' if proj_msg else 'no'}")
score_doc = "L10 rate (45%)" in tab or "L10 rate 45" in tab or "45%" in tab
print(f"  old score explanation present: {'yes — needs fix' if score_doc else 'no'}")

# show current _score first lines so Claude sees what's there
print("\n=== current _score method (first 20 lines) ===")
import re
m = re.search(r'    def _score\(self, pr[^\n]*\n', pr)
if m:
    body = pr[m.start():m.start()+900]
    for line in body.split("\n")[:22]:
        print(line)
