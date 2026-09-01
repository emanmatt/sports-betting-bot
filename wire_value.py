"""Wire the Value tab into app.py — makes all 3 edits safely in UTF-8."""
path = "dashboard/app.py"
src = open(path, encoding="utf-8").read()

# Edit 1: expand the tab tuple + st.tabs count
old_tabs = "tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12 = st.tabs(["
new_tabs = "tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12, tab13 = st.tabs(["
if old_tabs in src:
    src = src.replace(old_tabs, new_tabs)
    print("[1] tab tuple expanded to 13")
elif "tab13" in src:
    print("[1] already has tab13 — skipping")
else:
    print("[1] WARNING: tab line not found, check manually")

# Edit 2: add the Value label after the Parlays label
if '"💎 Value"' not in src:
    if '"🎰 Parlays",' in src:
        src = src.replace('"🎰 Parlays",', '"🎰 Parlays",\n    "💎 Value",')
        print("[2] Value label added after Parlays")
    else:
        # fallback: add before the closing of the tabs list
        print("[2] WARNING: couldn't find Parlays label — add '💎 Value' manually")
else:
    print("[2] Value label already present")

# Edit 3: append the content block if not there
if "with tab13:" not in src:
    src += '''

# ════════════════════════════════════════════════════════
# TAB 13: VALUE (real lines + edge)
# ════════════════════════════════════════════════════════
with tab13:
    try:
        from dashboard.value_tab import render_value_tab
        render_value_tab(selected_sport)
    except Exception as e:
        st.error(f"Value tab error: {e}")
'''
    print("[3] tab13 content block appended")
else:
    print("[3] tab13 block already present")

open(path, "w", encoding="utf-8").write(src)
print("Done. app.py updated.")

# Verify it still parses
import ast
try:
    ast.parse(open(path, encoding="utf-8").read())
    print("✓ app.py parses cleanly")
except SyntaxError as e:
    print(f"✗ SYNTAX ERROR: {e} — you may need to check manually")
