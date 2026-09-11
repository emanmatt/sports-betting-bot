"""
Phase 1: sport switcher shell.
1. config: SUPPORTED_SPORTS = ["MLB","NFL","NBA"]
2. app tab2 (Top Props) routes by sport: MLB->MLB board, NFL->NFL board,
   NBA-> 'season starts Oct 20' message. MLB path unchanged.
Backs up both files, auto-restores on error.
"""
import ast

# ---- 1. config ----
cfg_path = "config/settings.py"
cfg = open(cfg_path, encoding="utf-8").read()
cfg_orig = cfg
old_line = 'SUPPORTED_SPORTS = ["MLB"]'
new_line = 'SUPPORTED_SPORTS = ["MLB", "NFL", "NBA"]'
if old_line in cfg:
    cfg = cfg.replace(old_line, new_line)
    open(cfg_path + ".presport", "w", encoding="utf-8").write(cfg_orig)
    open(cfg_path, "w", encoding="utf-8").write(cfg)
    print("[1] config: SUPPORTED_SPORTS = MLB, NFL, NBA")
else:
    print(f"[1] config line not matched (current may already differ)")

# ---- 2. app tab2 routing ----
app_path = "dashboard/app.py"
app = open(app_path, encoding="utf-8").read()
app_orig = app

old_tab2 = '''with tab2:
    try:
        from dashboard.tophits_tab import render_tophits_tab
        render_tophits_tab(selected_sport)
    except Exception as e:
        st.error(f"Top Hits error: {e}")'''

new_tab2 = '''with tab2:
    try:
        if selected_sport == "NFL":
            from dashboard.nfl_tab import render_nfl_tab
            render_nfl_tab()
        elif selected_sport == "NBA":
            st.subheader("🏀 NBA Props")
            st.info("🏀 The 2026-27 NBA season starts **October 20, 2026**. "
                    "Full NBA prop analysis — the same ranking, value, parlay and "
                    "learning tools as MLB — will be live once games begin and "
                    "real data is available. Building it now would only produce "
                    "guesses; it'll be grounded in actual games at tip-off.")
        else:
            from dashboard.tophits_tab import render_tophits_tab
            render_tophits_tab(selected_sport)
    except Exception as e:
        st.error(f"Top Props error: {e}")'''

if old_tab2 in app:
    app = app.replace(old_tab2, new_tab2)
    open(app_path + ".presport", "w", encoding="utf-8").write(app_orig)
    open(app_path, "w", encoding="utf-8").write(app)
    print("[2] tab2 now routes by sport (MLB/NFL/NBA)")
else:
    print("[2] tab2 block not matched exactly — will report for manual")

# verify both parse
ok = True
for p, orig in [(cfg_path, cfg_orig), (app_path, app_orig)]:
    try:
        ast.parse(open(p, encoding="utf-8").read())
        print(f"\u2713 {p} parses cleanly")
    except SyntaxError as e:
        print(f"\u2717 {p} SYNTAX ERROR: {e}")
        open(p, "w", encoding="utf-8").write(orig)
        print(f"  restored {p}")
        ok = False
