"""Check if the NFL tab logs predictions, and where the ranked props land."""
nfl = open("dashboard/nfl_tab.py", encoding="utf-8").read()
print("=== does nfl_tab log or store props? ===")
for i, ln in enumerate(nfl.split("\n"), 1):
    if any(k in ln for k in ["log_predictions", "TrackRecord", "nfl_prop_ranks",
                             "session_state", "all_props", "st.success"]):
        print(f"{i:4}: {ln.rstrip()}")
