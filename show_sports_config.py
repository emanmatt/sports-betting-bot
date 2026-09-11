"""Show the SUPPORTED_SPORTS config and how selected_sport feeds the tabs."""
cfg = open("config/settings.py", encoding="utf-8").read()
import re
print("=== SUPPORTED_SPORTS / ALL_SPORTS in config ===")
for i, ln in enumerate(cfg.split("\n"), 1):
    if "SUPPORTED_SPORTS" in ln or "ALL_SPORTS" in ln or "SPORT" in ln.upper():
        print(f"{i:4}: {ln.rstrip()}")

print("\n=== how Top Props tab receives sport (line 286 area) ===")
app = open("dashboard/app.py", encoding="utf-8").read().split("\n")
for lo, hi in [(283, 290), (598, 605)]:
    for j in range(lo-1, min(hi, len(app))):
        print(f"{j+1:4}: {app[j].rstrip()}")
    print("   ---")
