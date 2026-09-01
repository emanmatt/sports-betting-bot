"""Wire the Parlay Calculator + Demon Slips tab into app.py (tab14), UTF-8 safe."""
path = "dashboard/app.py"
src = open(path, encoding="utf-8").read()

# Edit 1: expand tab tuple 13 -> 14
old = "tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12, tab13 = st.tabs(["
new = "tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12, tab13, tab14 = st.tabs(["
if old in src:
    src = src.replace(old, new)
    print("[1] tab tuple expanded to 14")
elif "tab14" in src:
    print("[1] already has tab14")
else:
    print("[1] WARNING: tab13 line not found — check manually")

# Edit 2: add label after Value
if '"🧮 Calc & Demons"' not in src:
    if '"💎 Value",' in src:
        src = src.replace('"💎 Value",', '"💎 Value",\n    "🧮 Calc & Demons",')
        print("[2] label added after Value")
    else:
        print("[2] WARNING: Value label not found — add manually")
else:
    print("[2] label already present")

# Edit 3: append content block
if "with tab14:" not in src:
    src += '''

# ════════════════════════════════════════════════════════
# TAB 14: PARLAY CALCULATOR + DEMON SLIPS
# ════════════════════════════════════════════════════════
with tab14:
    try:
        from dashboard.parlay_calc_tab import render_parlay_calc_tab
        render_parlay_calc_tab()
    except Exception as e:
        st.error(f"Calculator/Demons error: {e}")
'''
    print("[3] tab14 content block appended")
else:
    print("[3] tab14 block already present")

open(path, "w", encoding="utf-8").write(src)
import ast
try:
    ast.parse(open(path, encoding="utf-8").read())
    print("✓ app.py parses cleanly")
except SyntaxError as e:
    print(f"✗ SYNTAX ERROR: {e}")
