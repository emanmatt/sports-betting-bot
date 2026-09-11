"""Show the exact projected-message block and score line so Claude patches precisely."""
tab = open("dashboard/tophits_tab.py", encoding="utf-8").read()
lines = tab.split("\n")

# Find the projected message block
print("=== projected-message area ===")
for i, ln in enumerate(lines, 1):
    if "projected" in ln.lower() and ("st.info" in ln or "showing projected" in ln or "game(s)" in ln):
        # print a window around it
        lo = max(0, i-3); hi = min(len(lines), i+6)
        for j in range(lo, hi):
            print(f"{j+1:4}: {lines[j]}")
        print("    ---")
        break

print("\n=== score explanation line ===")
for i, ln in enumerate(lines, 1):
    if "**Score" in ln or "L10 rate" in ln:
        print(f"{i:4}: {ln}")
