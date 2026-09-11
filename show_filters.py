"""Show the current filter code in tophits_tab so Claude extends it correctly."""
tab = open("dashboard/tophits_tab.py", encoding="utf-8").read()
lines = tab.split("\n")

print("=== existing filter code (selectbox / filter / Game / Type / Prop) ===")
for i, ln in enumerate(lines, 1):
    if any(k in ln for k in ["selectbox", "st.multiselect", "filtered", "game_filter",
                              "type_filter", "prop_filter", "min_tier", "st.columns(",
                              "st.radio", '"Game"', '"Team"', '"Prop"']):
        print(f"{i:4}: {ln.rstrip()}")

print("\n=== the dataframe render + surrounding lines ===")
for i, ln in enumerate(lines, 1):
    if "st.dataframe" in ln or "Full Ranking" in ln or "pd.DataFrame(filtered)" in ln:
        lo = max(0, i-2); hi = min(len(lines), i+3)
        for j in range(lo, hi):
            print(f"{j+1:4}: {lines[j].rstrip()}")
        print("    ---")
