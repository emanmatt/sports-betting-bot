"""Check if line 172 is a multi-line string that my patch might break."""
lines = open("dashboard/tophits_tab.py", encoding="utf-8").read().split("\n")
print("Lines 168-180 (context around score doc):")
for i in range(167, 181):
    if i < len(lines):
        print(f"{i+1:4}: {lines[i]}")
