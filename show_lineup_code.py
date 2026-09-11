"""Show how the ranker handles confirmed vs projected, so Claude patches right."""
src = open("analysis/prop_ranker.py", encoding="utf-8").read()
import re

# Find references to confirmed / projected / lineup in rank_all_props
print("=== confirmed/projected references in prop_ranker ===")
for i, line in enumerate(src.split("\n"), 1):
    if any(k in line.lower() for k in ["confirmed", "projected", "get(\"status\"",
                                        "game_status", "lineup"]):
        print(f"{i:4}: {line.rstrip()}")

print("\n=== how tophits_tab builds lineups_data (confirmed flag) ===")
try:
    tab = open("dashboard/tophits_tab.py", encoding="utf-8").read()
    for i, line in enumerate(tab.split("\n"), 1):
        if any(k in line.lower() for k in ["confirmed", "projected",
                                            "get_lineup", "lineups_data.append",
                                            "\"confirmed\"", "status"]):
            print(f"{i:4}: {line.rstrip()}")
except Exception as e:
    print(e)
