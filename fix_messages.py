"""
Cosmetic message fixes ONLY (does not touch scoring — keeps the
lineup experiment clean):
1. Fix the "showing projected batters" message to be accurate when
   confirmed-only mode is on.
2. Update the outdated score-formula explanation text.
Backs up, auto-restores on error.
"""
import ast

tab_path = "dashboard/tophits_tab.py"
tab = open(tab_path, encoding="utf-8").read()
orig = tab

# --- Fix 1: the projected-batters info message ---
# Old message assumed projected players are shown. With confirmed-only
# on, they're NOT. Make the message conditional/accurate.
old_msg_variants = [
    ('st.info(f"ℹ️ {projected} game(s) don\'t have official lineups "\n'
     '                           "posted yet — showing projected batters from the active "\n'
     '                           "roster. Re-run once lineups drop (1-3 hrs before game) "\n'
     '                           "for confirmed batting orders.")'),
]
new_msg = ('if st.session_state.get("confirmed_only_toggle", True):\n'
           '                    st.info(f"ℹ️ {projected} game(s) have no confirmed lineup yet. "\n'
           '                           "Confirmed-only mode is ON, so those players are "\n'
           '                           "hidden until lineups post (1-3 hrs before game). "\n'
           '                           "Re-run then for a bettable board.")\n'
           '                else:\n'
           '                    st.info(f"ℹ️ {projected} game(s) don\\'t have official lineups "\n'
           '                           "posted yet — showing PROJECTED batters (not yet "\n'
           '                           "bettable). Re-run once lineups drop for confirmed "\n'
           '                           "batting orders.")')

fixed1 = False
for old in old_msg_variants:
    if old in tab:
        tab = tab.replace(old, new_msg)
        fixed1 = True
        break
print(f"[1] projected message: {'✓ fixed' if fixed1 else '✗ exact text not found (will report)'}")

# --- Fix 2: outdated score explanation ---
old_score_doc = ("**Score (0-100):** L10 rate (45%) + L15 rate (20%) + recent form + "
                 "weather + batting order. Tiers: A (70+), B (55+), C (40+), pass (<40).")
# try a few likely variants
score_doc_found = False
for variant in [
    "L10 rate (45%) + L15 rate (20%)",
    "L10 rate 45",
    "L10 (45%)",
]:
    if variant in tab:
        # replace the whole line containing it
        import re
        lines = tab.split("\n")
        for i, ln in enumerate(lines):
            if variant in ln:
                lines[i] = re.sub(
                    r'\*\*Score.*',
                    "**Score (0-100):** Driven mainly by recent form "
                    "(L10 + L15 hit rate). Matchup, park, weather and platoon "
                    "show as columns for context. Tiers: A (70+), B (55+), "
                    "C (40+), pass (<40).",
                    ln)
                score_doc_found = True
        tab = "\n".join(lines)
        break
print(f"[2] score explanation: {'✓ updated' if score_doc_found else '✗ text not found'}")

if tab != orig:
    open(tab_path + ".premsg", "w", encoding="utf-8").write(orig)
    open(tab_path, "w", encoding="utf-8").write(tab)

try:
    ast.parse(open(tab_path, encoding="utf-8").read())
    print("✓ tophits_tab.py parses cleanly")
except SyntaxError as e:
    print(f"✗ SYNTAX ERROR: {e}")
    open(tab_path, "w", encoding="utf-8").write(orig)
    print("  restored — tell Claude")
