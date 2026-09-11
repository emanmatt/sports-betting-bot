"""
Cosmetic message fixes ONLY. (Fixed escaping bug from v1.)
Does NOT touch scoring — keeps the lineup experiment clean.
Backs up, auto-restores on error.
"""
import ast, re

tab_path = "dashboard/tophits_tab.py"
tab = open(tab_path, encoding="utf-8").read()
orig = tab

# --- Fix 1: the projected-batters info message ---
# Find the st.info block that mentions "showing projected batters" and
# replace the whole st.info(...) call with a confirmed-only-aware version.
# We locate by the anchor phrase and replace the enclosing st.info(...).
anchor = "showing projected batters from the active"
if anchor in tab:
    # find the start of "st.info(" before the anchor
    a_idx = tab.find(anchor)
    start = tab.rfind("st.info(", 0, a_idx)
    # find the matching close: the ')' that ends this call, then end of line
    # crude but works: find the first '")' after anchor then the ')'
    close_paren = tab.find(")", a_idx)
    # build replacement using a triple-quoted new block (indent 16 spaces)
    indent = "                "
    new_block = (
        'if st.session_state.get("confirmed_only_toggle", True):\n'
        + indent + '    st.info(f"\u2139\ufe0f {projected} game(s) have no confirmed '
        'lineup yet. Confirmed-only mode is ON, so those players are hidden until '
        'lineups post (1-3 hrs before game). Re-run then for a bettable board.")\n'
        + indent + 'else:\n'
        + indent + '    st.info(f"\u2139\ufe0f {projected} game(s) do not have official '
        'lineups posted yet \u2014 showing PROJECTED batters (not yet bettable). '
        'Re-run once lineups drop for confirmed batting orders.")'
    )
    tab = tab[:start] + new_block + tab[close_paren+1:]
    print("[1] projected message: \u2713 fixed")
else:
    print("[1] projected message: \u2717 anchor not found")

# --- Fix 2: outdated score explanation ---
score_doc_found = False
for variant in ["L10 rate (45%)", "L10 rate 45", "L10 (45%)", "45%"]:
    if variant in tab:
        lines = tab.split("\n")
        for i, ln in enumerate(lines):
            if variant in ln and "Score" in ln:
                lines[i] = re.sub(
                    r'\*\*Score.*',
                    "**Score (0-100):** Driven mainly by recent form (L10 + L15 "
                    "hit rate). Matchup, park, weather and platoon show as columns "
                    "for context. Tiers: A (70+), B (55+), C (40+), pass (<40).",
                    ln)
                score_doc_found = True
        tab = "\n".join(lines)
        break
print(f"[2] score explanation: {'\u2713 updated' if score_doc_found else '\u2717 not found (minor, skip)'}")

if tab != orig:
    open(tab_path + ".premsg", "w", encoding="utf-8").write(orig)
    open(tab_path, "w", encoding="utf-8").write(tab)

try:
    ast.parse(open(tab_path, encoding="utf-8").read())
    print("\u2713 tophits_tab.py parses cleanly")
except SyntaxError as e:
    print(f"\u2717 SYNTAX ERROR: {e}")
    open(tab_path, "w", encoding="utf-8").write(orig)
    print("  restored original \u2014 tell Claude")
