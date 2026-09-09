"""Wire the NFL Props tab into app.py (tab15), UTF-8 safe, backs up."""
path = "dashboard/app.py"
src = open(path, encoding="utf-8").read()
orig = src

old = "tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12, tab13, tab14 = st.tabs(["
new = "tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12, tab13, tab14, tab15 = st.tabs(["
if old in src:
    src = src.replace(old, new)
    print("[1] tab tuple expanded to 15")
elif "tab15" in src:
    print("[1] already has tab15")
else:
    print("[1] WARNING: tab14 line not found")

if '"🏈 NFL Props"' not in src:
    if '"🧮 Calc & Demons",' in src:
        src = src.replace('"🧮 Calc & Demons",', '"🧮 Calc & Demons",\n    "🏈 NFL Props",')
        print("[2] NFL label added")
    else:
        print("[2] WARNING: Calc label not found — add manually")
else:
    print("[2] label already present")

if "with tab15:" not in src:
    src += '''

# ════════════════════════════════════════════════════════
# TAB 15: NFL PROPS
# ════════════════════════════════════════════════════════
with tab15:
    try:
        from dashboard.nfl_tab import render_nfl_tab
        render_nfl_tab()
    except Exception as e:
        st.error(f"NFL tab error: {e}")
'''
    print("[3] tab15 content block appended")
else:
    print("[3] tab15 block already present")

if src != orig:
    open(path + ".prenfl", "w", encoding="utf-8").write(orig)
    open(path, "w", encoding="utf-8").write(src)

import ast
try:
    ast.parse(open(path, encoding="utf-8").read())
    print("✓ app.py parses cleanly")
except SyntaxError as e:
    print(f"✗ SYNTAX ERROR: {e}")
    open(path, "w", encoding="utf-8").write(orig)
    print("Restored original — tell Claude.")
