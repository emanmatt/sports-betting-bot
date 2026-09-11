"""Show the top of app.py — how sport is currently selected and how tabs start."""
src = open("dashboard/app.py", encoding="utf-8").read()
lines = src.split("\n")

print("=== sport selection / selectbox / SUPPORTED_SPORTS references ===")
for i, ln in enumerate(lines, 1):
    if any(k in ln for k in ["selected_sport", "SUPPORTED_SPORTS", "sport", "st.sidebar",
                              "st.selectbox", "set_page_config", "st.title", "st.tabs"]):
        print(f"{i:4}: {ln.rstrip()}")

print("\n=== first 40 lines of app.py (structure) ===")
for i in range(min(40, len(lines))):
    print(f"{i+1:4}: {lines[i].rstrip()}")
