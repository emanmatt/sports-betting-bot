"""
dashboard/game_analysis_tab.py

Primary view: a Claude-written framework analysis per game — not stat tables.
- Analyze ONE game (fast, one Claude call) or the whole slate.
- Save any analysis to the database, so it survives app reboots.
- Rate saved analyses 0-5 stars; best-rated sort to the top.
Uses the Anthropic key (no OddsAPI credits).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

SPORT = "NFL"


def _edge_caption(edge_plays):
    if not edge_plays:
        return
    try:
        st.caption("Model edge plays fed to the analysis: " +
                   " · ".join(f"{n} {pl} ({float(hr):.0f}%, {t})"
                              for n, pl, hr, t in edge_plays[:5]))
    except Exception:
        pass


def render_game_analysis_tab():
    st.subheader("🧠 Game Analysis")
    st.caption("A framework breakdown per game — the lean, situational factors, "
               "counter-case, and confidence — from the model's edge data + live "
               "injury/news search. Uses Anthropic credits (not OddsAPI). "
               "Rush-yard props are the proven edge.")

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

    game_by_matchup = {f"{g.away_team} @ {g.home_team}": g for g in upcoming}

    # ---- Analyze controls ----
    st.markdown(f"**{len(upcoming)} games this week.** "
                "Analyze one game (seconds) or the whole slate (~a minute or two).")
    pick = st.selectbox("Pick a game", list(game_by_matchup.keys()))
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        run_one = st.button("⚡ Analyze This Game", type="primary")
    with c2:
        run_all = st.button("🧠 Analyze All")
    with c3:
        if st.button("🗑️ Clear results"):
            st.session_state.pop("game_analyses", None)
            st.rerun()

    results = st.session_state.setdefault("game_analyses", {})

    if run_one:
        from analysis.game_analysis import analyze_nfl_game
        g = game_by_matchup[pick]
        with st.spinner(f"Analyzing {pick}…"):
            try:
                results[pick] = analyze_nfl_game(g, ranker)
            except Exception as e:
                results[pick] = {"matchup": pick,
                                 "writeup": f"Analysis failed: {e}",
                                 "edge_plays": []}
        st.session_state["game_analyses"] = results
        st.rerun()

    if run_all:
        from analysis.game_analysis import analyze_nfl_game
        prog = st.progress(0)
        items = list(game_by_matchup.items())
        for i, (m, g) in enumerate(items):
            try:
                results[m] = analyze_nfl_game(g, ranker)
            except Exception as e:
                results[m] = {"matchup": m,
                              "writeup": f"Analysis failed: {e}",
                              "edge_plays": []}
            prog.progress((i + 1) / len(items))
        prog.empty()
        st.session_state["game_analyses"] = results
        st.rerun()

    # ---- Saved store (DB) ----
    store_ok = True
    try:
        from analysis.saved_analyses import (save_analysis, list_saved,
                                             set_rating, delete_saved)
    except Exception as e:
        store_ok = False
        st.warning(f"Saved-analysis store unavailable: {e}")

    # ---- Fresh (unsaved) results this session ----
    if results:
        st.divider()
        st.markdown("### New analyses (this session)")
        for matchup, data in results.items():
            failed = str(data.get("writeup", "")).startswith("Analysis failed")
            with st.expander(f"🏈 {matchup}", expanded=(len(results) == 1)):
                st.markdown(data["writeup"])
                _edge_caption(data.get("edge_plays"))
                if store_ok and not failed:
                    if st.button("💾 Save", key=f"save_{matchup}"):
                        try:
                            save_analysis(matchup, SPORT, data["writeup"],
                                          data.get("edge_plays", []))
                            st.success("Saved — rate it in the section below.")
                        except Exception as e:
                            st.error(f"Save failed: {e}")

    # ---- Saved & rated (from DB) ----
    if store_ok:
        try:
            saved = list_saved(SPORT)
        except Exception as e:
            saved = []
            st.warning(f"Couldn't load saved analyses: {e}")
        st.divider()
        st.markdown(f"### ⭐ Saved & rated ({len(saved)})")
        if not saved:
            st.info("Save an analysis above to start rating your best writeups.")
        for row in saved:
            rating = int(row.get("rating", 0) or 0)
            stars = "★" * rating + "☆" * (5 - rating)
            with st.expander(f"{stars}  {row['matchup']}", expanded=False):
                st.markdown(row["writeup"])
                _edge_caption(row.get("edge_plays"))
                rc1, rc2, rc3 = st.columns([2, 1, 1])
                with rc1:
                    new_rating = st.slider("Rating", 0, 5, rating,
                                           key=f"rate_{row['id']}")
                with rc2:
                    if st.button("Save rating", key=f"saverate_{row['id']}"):
                        try:
                            set_rating(row["id"], new_rating)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Rating failed: {e}")
                with rc3:
                    if st.button("🗑️ Delete", key=f"del_{row['id']}"):
                        try:
                            delete_saved(row["id"])
                            st.rerun()
                        except Exception as e:
                            st.error(f"Delete failed: {e}")
