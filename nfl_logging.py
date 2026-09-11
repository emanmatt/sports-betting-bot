"""
Wire the NFL tab to log predictions with sport='NFL' so they enter
the track record (and later get graded). Anchors on the session_state
store line. Backs up, auto-restores on error.
"""
import ast

path = "dashboard/nfl_tab.py"
src = open(path, encoding="utf-8").read()
orig = src

anchor = '    st.session_state["nfl_prop_ranks"] = all_props'
if anchor in src:
    inject = (anchor + '\n\n'
              '    # Log NFL predictions to the track record (sport-tagged) so\n'
              '    # they accumulate for grading + the learning loop, same as MLB.\n'
              '    try:\n'
              '        from analysis.track_record import TrackRecord\n'
              '        tr = TrackRecord()\n'
              '        tr.log_predictions(all_props, top_n=20, sport="NFL")\n'
              '        tr.close()\n'
              '    except Exception:\n'
              '        pass')
    src = src.replace(anchor, inject, 1)
    print("[1] NFL logging call added")
else:
    print("[1] anchor not matched")

if src != orig:
    open(path + ".prelog", "w", encoding="utf-8").write(orig)
    open(path, "w", encoding="utf-8").write(src)

try:
    ast.parse(open(path, encoding="utf-8").read())
    print("✓ nfl_tab.py parses cleanly")
except SyntaxError as e:
    print(f"✗ SYNTAX ERROR: {e}")
    open(path, "w", encoding="utf-8").write(orig)
    print("  restored")
