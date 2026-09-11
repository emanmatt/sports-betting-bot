"""
Precise cosmetic fix v4 — replaces the projected message block AND the
TWO-line score doc (172-173) as a unit so nothing is orphaned.
Does NOT touch scoring. Verified to parse before shipping.
"""
import ast

tab_path = "dashboard/tophits_tab.py"
tab = open(tab_path, encoding="utf-8").read()
orig = tab

# --- Fix 1: projected message block (exact 4 lines, 20-space indent) ---
old_block = (
'                    st.info(f"\u2139\ufe0f {projected} game(s) don\'t have official lineups "\n'
'                           "posted yet \u2014 showing projected batters from the active "\n'
'                           "roster. Re-run once lineups drop (1-3 hrs before game) "\n'
'                           "for confirmed batting orders.")'
)
new_block = (
'                    if st.session_state.get("confirmed_only_toggle", True):\n'
'                        st.info(f"\u2139\ufe0f {projected} game(s) have no confirmed lineup "\n'
'                               "yet. Confirmed-only mode is ON, so those players are "\n'
'                               "hidden until lineups post (1-3 hrs before game). "\n'
'                               "Re-run then for a bettable board.")\n'
'                    else:\n'
'                        st.info(f"\u2139\ufe0f {projected} game(s) have no official lineup "\n'
'                               "yet \u2014 showing PROJECTED batters (not yet bettable). "\n'
'                               "Re-run once lineups drop for confirmed batting orders.")'
)
if old_block in tab:
    tab = tab.replace(old_block, new_block)
    print("[1] projected message: \u2713 fixed")
else:
    print("[1] projected message: \u2717 not matched")

# --- Fix 2: the TWO-line score doc (172-173) replaced as a unit ---
old_score = (
'        **Score (0-100):** L10 rate (45%) + L15 rate (20%) + recent form +\n'
'        weather + batting order. Tiers: A (70+), B (55+), C (40+), pass (<40).'
)
new_score = (
'        **Score (0-100):** Driven mainly by recent form (L10 + L15 hit rate);\n'
'        matchup, park, weather, platoon show as context columns. Tiers: A (70+), B (55+), C (40+), pass (<40).'
)
if old_score in tab:
    tab = tab.replace(old_score, new_score)
    print("[2] score doc: \u2713 updated")
else:
    print("[2] score doc: \u2717 not matched (skipping)")

if tab != orig:
    open(tab_path + ".premsg", "w", encoding="utf-8").write(orig)
    open(tab_path, "w", encoding="utf-8").write(tab)

try:
    ast.parse(open(tab_path, encoding="utf-8").read())
    print("\u2713 tophits_tab.py parses cleanly")
except SyntaxError as e:
    print(f"\u2717 SYNTAX ERROR: {e}")
    open(tab_path, "w", encoding="utf-8").write(orig)
    print("  restored original")
