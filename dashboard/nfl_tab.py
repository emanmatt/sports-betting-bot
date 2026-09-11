"""
dashboard/nfl_tab.py

The 🏈 NFL Props tab — football prop rankings, isolated from the MLB
board so it never slows it down (this code only runs when you open the
tab and click a button).

Efficient by design:
  - Default: rank ONE game (pick a matchup) — fast, few API calls
  - Optional: rank the full slate (slower, warned)
NFL ranking pulls rosters + game logs from ESPN (free, no credits),
so nothing here spends OddsAPI credits. Real lines/edge come from the
Value tab like MLB.

Week 1 honesty: with no 2026 games yet, everything runs on 2025 data —
the board labels which season each number came from.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd


def render_nfl_tab():
    st.subheader("🏈 NFL Props")
    st.caption("Prop rankings for QBs and skill players. Early season leans on "
               "last year's data (labeled) and sharpens as 2026 games play. "
               "Free ESPN data — spends no OddsAPI credits.")

    try:
        from analysis.nfl_ranker import NFLRanker
        ranker = NFLRanker()
    except Exception as e:
        st.error(f"NFL ranker unavailable: {e}")
        return

    # Get this week's games (one cheap call)
    try:
        games = ranker.nfl.get_todays_games()
    except Exception as e:
        st.error(f"Couldn't load NFL schedule: {e}")
        return

    if not games:
        st.info("No NFL games found for this week yet.")
        return

    # Show the slate
    with st.expander(f"🗓️ This week — {len(games)} games", expanded=False):
        for g in games:
            status = ranker.nfl.classify_status(g.status)
            badge = {"final": "✅ Final", "live": "🔴 LIVE"}.get(status, "Upcoming")
            st.markdown(f"**{g.away_team} @ {g.home_team}** — "
                       f"{g.game_time[:10]} · {badge}")

    st.divider()

    # Mode: one game (fast) or full slate (slow)
    mode = st.radio("Ranking mode",
                   ["⚡ One game (fast)", "🐢 Full slate (slower)"],
                   horizontal=True)

    if mode.startswith("⚡"):
        matchups = [f"{g.away_team} @ {g.home_team}" for g in games
                   if ranker.nfl.classify_status(g.status) != "final"]
        choice = st.selectbox("Pick a game", matchups)
        if st.button("🏈 Rank This Game", type="primary"):
            g = next((x for x in games
                     if f"{x.away_team} @ {x.home_team}" == choice), None)
            if g:
                _rank_and_show(ranker, [g])

    else:
        st.warning("Full slate pulls every team's roster + player logs from "
                  "ESPN — takes ~1-2 minutes. Use one-game mode for speed.")
        if st.button("🐢 Rank Full Slate"):
            _rank_and_show(ranker, [g for g in games
                          if ranker.nfl.classify_status(g.status) != "final"])


def _rank_and_show(ranker, games):
    all_props = []
    prog = st.progress(0)
    for i, g in enumerate(games):
        status = ranker.nfl.classify_status(g.status)
        matchup = f"{g.away_team} @ {g.home_team}"
        for team_id, team_name, opp_name in [
            (g.home_team_id, g.home_team, g.away_team),
            (g.away_team_id, g.away_team, g.home_team),
        ]:
            try:
                if ranker.inactives:
                    ranker.inactives.load_team(team_id)
                roster = ranker.nfl.get_team_roster(team_id)
                for player in roster:
                    all_props.extend(
                        ranker.rank_player(player, team_name, opp_name,
                                          matchup, status))
            except Exception:
                continue
        prog.progress((i + 1) / len(games))
    prog.empty()

    all_props.sort(key=lambda x: x.score, reverse=True)

    if not all_props:
        st.warning("No rankable props — players may lack sufficient data.")
        return

    # Store for the parlay/value tools to reuse (same shape they expect)
    st.session_state["nfl_prop_ranks"] = all_props

    # Log NFL predictions to the track record (sport-tagged) so
    # they accumulate for grading + the learning loop, same as MLB.
    try:
        from analysis.track_record import TrackRecord
        tr = TrackRecord()
        tr.log_predictions(all_props, top_n=20, sport="NFL")
        tr.close()
    except Exception:
        pass

    rows = ranker.to_table_rows(all_props, limit=100)
    st.success(f"Ranked {len(all_props)} NFL props.")

    # Top 5 highlight
    st.markdown("### 🏈 Top 5 Plays")
    for p in all_props[:5]:
        conf = " ⚠️ thin data" if p.low_confidence else ""
        st.markdown(f"**{p.player_name}** ({p.position}, {p.team}) — "
                   f"{p.prop_label} · hit {p.hit_rate:.0f}% · "
                   f"tier {p.tier}{conf}")

    st.divider()
    st.markdown("### 📊 Full NFL Ranking")
    df = pd.DataFrame(rows)
    # numeric hit% for sorting
    if not df.empty and "Hit %" in df.columns:
        df["Hit % (num)"] = df["Hit %"].str.replace("%", "").astype(float)
    st.dataframe(df, hide_index=True, use_container_width=True, height=500)

    st.info("**Data** column shows which season each number came from. In "
           "Week 1 that's 2025 (last year) — projections, not current form. "
           "⚠️ thin = small sample (rookie/backup), treated cautiously. "
           "As 2026 games play, the board shifts to current-season data.")
