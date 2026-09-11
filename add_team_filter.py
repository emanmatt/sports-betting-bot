"""
Add a Team filter to the existing filter row in tophits_tab.
Extends the current f1/f2/f3 columns to include Team, and adds the
filter logic. Exact-match against the confirmed current code.
"""
import ast

tab_path = "dashboard/tophits_tab.py"
tab = open(tab_path, encoding="utf-8").read()
orig = tab

# 1. Change the 3-column filter row to 4 columns and add Team selectbox.
old_cols = '    f1, f2, f3 = st.columns(3)'
new_cols = '    f1, f2, f3, f4 = st.columns(4)'
if old_cols in tab:
    tab = tab.replace(old_cols, new_cols)
    print("[1] filter row -> 4 columns")
else:
    print("[1] filter columns line not matched")

# 2. Add the Team selectbox after the Min Tier selectbox block.
old_tier = '''        min_tier = st.selectbox("Min Tier", ["All", "A", "B", "C"])'''
new_tier = '''        min_tier = st.selectbox("Min Tier", ["All", "A", "B", "C"])
    with f4:
        teams_list = sorted(set(r["Team"] for r in rows if r.get("Team")))
        team_filter = st.selectbox("Team", ["All Teams"] + teams_list)'''
if old_tier in tab:
    tab = tab.replace(old_tier, new_tier)
    print("[2] Team selectbox added")
else:
    print("[2] Min Tier line not matched")

# 3. Add the team filter logic alongside the others.
old_filt = '''    if prop_filter != "All":
        filtered = [r for r in filtered if r["Prop"] == prop_filter]'''
new_filt = '''    if prop_filter != "All":
        filtered = [r for r in filtered if r["Prop"] == prop_filter]
    if team_filter != "All Teams":
        filtered = [r for r in filtered if r.get("Team") == team_filter]'''
if old_filt in tab:
    tab = tab.replace(old_filt, new_filt)
    print("[3] Team filter logic added")
else:
    print("[3] prop filter block not matched")

if tab != orig:
    open(tab_path + ".prefilter", "w", encoding="utf-8").write(orig)
    open(tab_path, "w", encoding="utf-8").write(tab)

try:
    ast.parse(open(tab_path, encoding="utf-8").read())
    print("\u2713 tophits_tab.py parses cleanly")
except SyntaxError as e:
    print(f"\u2717 SYNTAX ERROR: {e}")
    open(tab_path, "w", encoding="utf-8").write(orig)
    print("  restored original")
