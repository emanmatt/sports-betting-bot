"""
Wire NFL auto-grading: after the NFL board logs predictions, also grade
any past pending NFL predictions automatically (mirrors MLB's flow).
Anchors on the NFL logging block we added earlier. Backs up, restores on error.
"""
import ast

path = "dashboard/nfl_tab.py"
src = open(path, encoding="utf-8").read()
orig = src

# Anchor: the logging block we added. Add grading right after tr.close().
anchor = '''    try:
        from analysis.track_record import TrackRecord
        tr = TrackRecord()
        tr.log_predictions(all_props, top_n=20, sport="NFL")
        tr.close()
    except Exception:
        pass'''

new_block = '''    try:
        from analysis.track_record import TrackRecord
        tr = TrackRecord()
        tr.log_predictions(all_props, top_n=20, sport="NFL")
        tr.close()
    except Exception:
        pass

    # Auto-grade past pending NFL predictions against real results
    # (runs itself each time you rank — no manual command needed).
    try:
        from analysis.nfl_grader import NFLGrader
        graded = NFLGrader().grade_pending()
        if graded:
            st.caption(f"\U0001F4CA Learning loop: auto-graded {graded} past "
                       "NFL prediction(s) against results.")
    except Exception:
        pass'''

if anchor in src:
    src = src.replace(anchor, new_block, 1)
    print("[1] NFL auto-grade wired after logging")
else:
    print("[1] logging anchor not matched — check manually")

if src != orig:
    open(path + ".preautograde", "w", encoding="utf-8").write(orig)
    open(path, "w", encoding="utf-8").write(src)

try:
    ast.parse(open(path, encoding="utf-8").read())
    print("\u2713 nfl_tab.py parses cleanly")
except SyntaxError as e:
    print(f"\u2717 SYNTAX ERROR: {e}")
    open(path, "w", encoding="utf-8").write(orig)
    print("  restored")
