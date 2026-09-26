"""
dashboard/game_analysis_tab.py

Primary view: a Claude-written framework analysis for every game, instead
of stat tables. Analyze-all runs the whole slate in one click; results are
cached in session so re-viewing costs nothing extra.
Uses the Anthropic key (no OddsAPI credits).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st


def render_game_analysis_tab():
    st.subheader("🧠 Game Analysis")
    st.caption("A framework breakdown for every game — the lean, situational "
               "factors, counter-case, and confidence — built from the model's "
               "edge data + live injury/news search. Uses Anthropic credits "
               "(not OddsAPI). Rush-yard props are the proven edge.")

    try:
        from analysis.nfl_ranker import NFLRanker
        ranker = NFLRanker()
        games = ranker.nfl.get_todays_games()
    except Exception as e:
        st.error(f"Couldn't load games: {e}")
        return

    upcoming = [g for g in games
                if ranker.nfl.classify_status(g.status) != "final"]
    if not upcoming:
        st.info("No upcoming games this week.")
        return

    st.markdown(f"**{len(upcoming)} games this week.** Analyze-all makes one "
               "Claude call per game — ~{n} calls, a minute or two.".replace(
                   "{n}", str(len(upcoming))))
    col1, col2 = st.columns([1, 1])
    with col1:
        run_all = st.button("🧠 Analyze All Games", type="primary")
    with col2:
        if st.button("🗑️ Clear cached analysis"):
            st.session_state.pop("game_analyses", None)
            st.rerun()

    if run_all:
        from analysis.game_analysis import analyze_nfl_game
        results = {}
        prog = st.progress(0)
        for i, g in enumerate(upcoming):
            try:
                results[f"{g.away_team} @ {g.home_team}"] = analyze_nfl_game(g, ranker)
            except Exception as e:
                results[f"{g.away_team} @ {g.home_team}"] = {
                    "matchup": f"{g.away_team} @ {g.home_team}",
                    "writeup": f"Analysis failed: {e}", "edge_plays": []}
            prog.progress((i + 1) / len(upcoming))
        prog.empty()
        st.session_state["game_analyses"] = results
        st.success(f"Analyzed {len(results)} games.")

    analyses = st.session_state.get("game_analyses", {})
    if not analyses:
        st.info("Click **Analyze All Games** to generate breakdowns.")
        return

    st.divider()
    for matchup, data in analyses.items():
        with st.expander(f"🏈 {matchup}", expanded=False):
            st.markdown(data["writeup"])
            if data.get("edge_plays"):
                st.caption("Model edge plays fed to the analysis: " +
                          " · ".join(f"{n} {pl} ({hr:.0f}%, {t})"
                                     for n, pl, hr, t in data["edge_plays"][:5]))
