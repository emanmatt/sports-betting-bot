"""
Enforce confirmed-lineup-only ranking (the audit's #1 fix).
1. prop_ranker.rank_all_props gets a confirmed_only param that skips
   games whose lineup isn't officially confirmed.
2. tophits_tab adds a 'Confirmed lineups only' toggle (ON by default).
Backs up both files, auto-restores on syntax error.
"""
import re, ast

# ---------- 1. Patch prop_ranker.py ----------
pr_path = "analysis/prop_ranker.py"
src = open(pr_path, encoding="utf-8").read()
orig_pr = src

# Add confirmed_only param to rank_all_props signature
m = re.search(r'def rank_all_props\(self, lineups_data: list,\s*\n?\s*([^)]*)\)', src)
if "confirmed_only" not in src:
    # insert param — find the signature and add it
    sig = re.search(r'(def rank_all_props\(self, lineups_data: list,[^)]*)\)', src, re.DOTALL)
    if sig:
        newsig = sig.group(1) + ", confirmed_only: bool = False)"
        src = src.replace(sig.group(0), newsig, 1)
        print("[1a] confirmed_only param added")
    else:
        print("[1a] WARNING: signature not found")

# Add the skip logic right after 'for game in lineups_data:'
loop_anchor = "        for game in lineups_data:\n"
if loop_anchor in src and "confirmed_only and not game.get" not in src:
    skip = (loop_anchor +
            "            # Confirmed-lineup enforcement (audit fix): skip games\n"
            "            # whose official lineup isn't posted, so projected/\n"
            "            # benched players never reach the bettable board.\n"
            "            if confirmed_only and not game.get(\"confirmed\", False):\n"
            "                continue\n")
    src = src.replace(loop_anchor, skip, 1)
    print("[1b] skip-projected logic added")
else:
    print("[1b] loop anchor not found or already patched")

if src != orig_pr:
    open(pr_path + ".preconfirm", "w", encoding="utf-8").write(orig_pr)
    open(pr_path, "w", encoding="utf-8").write(src)

try:
    ast.parse(open(pr_path, encoding="utf-8").read())
    print("✓ prop_ranker.py parses cleanly")
except SyntaxError as e:
    print(f"✗ prop_ranker SYNTAX ERROR: {e}")
    open(pr_path, "w", encoding="utf-8").write(orig_pr)
    print("  restored prop_ranker")
    raise SystemExit

# ---------- 2. Patch tophits_tab.py ----------
tab_path = "dashboard/tophits_tab.py"
tab = open(tab_path, encoding="utf-8").read()
orig_tab = tab

# Add a toggle before the rank button area. Anchor on the fetch/rank button.
# We add a session-backed checkbox near the top of the render function.
if "confirmed_only" not in tab:
    # Insert the toggle right after the subheader/caption. Anchor on first st.button or the intro markdown.
    anchor = 'st.markdown("Pulls today\'s confirmed lineups + probable pitchers and "'
    if anchor in tab:
        inject = (anchor.replace('st.markdown(', 'st.markdown(', 1))  # keep line
        toggle = ('\n    confirmed_only = st.checkbox(\n'
                  '        "✅ Confirmed lineups only (recommended — audit showed "\n'
                  '        "betting projected players costs ~5-7% hit rate)",\n'
                  '        value=True, key="confirmed_only_toggle")\n')
        # place the toggle right after the caption markdown line ends
        idx = tab.find(anchor)
        line_end = tab.find("\n", idx)
        # the markdown call may span multiple lines; find the closing ")" then newline
        close = tab.find(")", idx)
        close_nl = tab.find("\n", close)
        tab = tab[:close_nl+1] + toggle + tab[close_nl+1:]
        print("[2a] confirmed_only toggle added to tab")
    else:
        print("[2a] WARNING: caption anchor not found — toggle NOT added, add manually")
else:
    print("[2a] toggle already present")

# Pass confirmed_only into the rank_all_props call
if "rank_all_props(lineups_data, weather_by_venue)" in tab:
    tab = tab.replace(
        "rank_all_props(lineups_data, weather_by_venue)",
        "rank_all_props(lineups_data, weather_by_venue, "
        "confirmed_only=st.session_state.get('confirmed_only_toggle', True))")
    print("[2b] confirmed_only passed into ranker call")
elif "confirmed_only=" in tab:
    print("[2b] already passing confirmed_only")
else:
    print("[2b] WARNING: rank_all_props call not found in expected form — check manually")

if tab != orig_tab:
    open(tab_path + ".preconfirm", "w", encoding="utf-8").write(orig_tab)
    open(tab_path, "w", encoding="utf-8").write(tab)

try:
    ast.parse(open(tab_path, encoding="utf-8").read())
    print("✓ tophits_tab.py parses cleanly")
except SyntaxError as e:
    print(f"✗ tophits_tab SYNTAX ERROR: {e}")
    open(tab_path, "w", encoding="utf-8").write(orig_tab)
    print("  restored tophits_tab — tell Claude")
