"""
dashboard/tophits_tab.py

The "Top Hits" tab — ranks batter hit props for today's games
using confirmed lineups + game logs + weather + matchup.
No OddsAPI credits needed. Shows a ranked table strongest→weakest,
plus a Claude summary of the top plays.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd


def render_tophits_tab(selected_sport: str):
    st.subheader("🔥 Top Hits — Ranked Batter Plays")
    st.caption("Combines confirmed lineups, L10/L15 hit rates, recent form, "
               "weather, batting order, and pitcher matchup. No betting-line "
               "credits needed — pure data ranking.")

    if selected_sport != "MLB":
        st.info("Top Hits ranking is currently MLB-only.")
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("Pulls today's confirmed lineups from MLB.com and ranks "
                    "every batter by hit likelihood.")
    with col2:
        run = st.button("🔥 Rank Today's Hits", type="primary",
                       use_container_width=True)

    if run:
        with st.spinner("Pulling lineups, weather, and game logs..."):
            try:
                from data_ingestion.official.mlb_client import MLBClient
                from data_ingestion.official.weather_engine import WeatherEngine
                from analysis.hits_ranker import HitsRanker

                mlb = MLBClient()
                weather = WeatherEngine()

                # Get today's games with lineups
                games = mlb.get_todays_games()
                lineups_data = []
                weather_by_venue = {}

                progress = st.progress(0)
                for i, g in enumerate(games):
                    lineup = mlb.get_lineup(g.game_pk)
                    # Get weather for venue
                    if g.venue and g.venue not in weather_by_venue:
                        weather_by_venue[g.venue] = weather.get_stadium_weather(g.venue)

                    lineups_data.append({
                        "game": f"{g.away_team} @ {g.home_team}",
                        "home_team": g.home_team,
                        "away_team": g.away_team,
                        "venue": g.venue,
                        "home_pitcher": g.home_pitcher,
                        "away_pitcher": g.away_pitcher,
                        "home_lineup": lineup.get("home", []),
                        "away_lineup": lineup.get("away", []),
                        "confirmed": lineup.get("confirmed", False),
                    })
                    progress.progress((i + 1) / max(len(games), 1))
                progress.empty()

                # Rank
                ranker = HitsRanker()
                plays = ranker.rank_todays_hits(lineups_data, weather_by_venue)
                rows = ranker.to_table_rows(plays, limit=40)
                ranker.close()

                st.session_state["hit_plays"] = plays
                st.session_state["hit_rows"] = rows

                confirmed_count = sum(1 for l in lineups_data if l["confirmed"])
                st.success(f"Ranked {len(plays)} batters across "
                          f"{confirmed_count} confirmed lineups!")
            except Exception as e:
                st.error(f"Ranking failed: {e}")
                import traceback
                st.caption(traceback.format_exc()[:500])

    rows = st.session_state.get("hit_rows", [])
    plays = st.session_state.get("hit_plays", [])

    if not rows:
        st.info("Click 'Rank Today's Hits' to generate the ranking.")
        st.markdown("""
        **How the score is built (0-100):**
        - **L10 hit rate** (45%) — how often they got a hit in last 10 games
        - **L15 hit rate** (20%) — stability over a bigger sample
        - **Recent form** (15%) — hot streaks boost the score
        - **Weather** (10%) — wind blowing out / hot temps
        - **Batting order** (10%) — top of order = more at-bats

        **Tiers:** A (70+) = strongest, B (55+), C (40+), pass (<40)
        """)
        return

    # Summary metrics
    tier_a = sum(1 for r in rows if r["Tier"] == "A")
    tier_b = sum(1 for r in rows if r["Tier"] == "B")

    m1, m2, m3 = st.columns(3)
    m1.metric("🅰️ Tier A Plays", tier_a)
    m2.metric("🅱️ Tier B Plays", tier_b)
    m3.metric("Total Ranked", len(rows))

    st.divider()

    # ── Top 5 highlighted ──────────────────────────────────────────────
    st.markdown("### 🏆 Top 5 Hit Plays")
    for r in rows[:5]:
        tier_color = {"A": "#4CAF50", "B": "#2196F3",
                     "C": "#ff9800"}.get(r["Tier"], "#888")
        st.markdown(
            f"<div style='background:#1c2333;border-left:4px solid {tier_color};"
            f"border-radius:8px;padding:12px;margin:6px 0'>"
            f"<b>#{r['Rank']} {r['Player']}</b> ({r['Team']}) "
            f"— Tier {r['Tier']} | Score: {r['Score']}<br>"
            f"L10: <b>{r['L10 Hit%']}</b> | L15: {r['L15 Hit%']} | "
            f"Avg: {r['Avg H']} H/game | L5: {r['L5 Avg']} | {r['Trend']}<br>"
            f"Batting {r['Order']} vs {r['vs Pitcher']}"
            f"</div>",
            unsafe_allow_html=True
        )

    st.divider()

    # ── Full sortable table ────────────────────────────────────────────
    st.markdown("### 📊 Full Ranking")
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True, height=500)

    # ── Claude summary of top plays ────────────────────────────────────
    st.divider()
    if st.button("🤖 Get Claude's Take on Top Plays"):
        with st.spinner("Claude analyzing the top plays..."):
            try:
                import anthropic
                from config.settings import ANTHROPIC_API_KEY
                from analysis.system_prompt import MASTER_SYSTEM_PROMPT

                client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

                # Build context from top 10
                top10 = rows[:10]
                context = "TOP RANKED HIT PLAYS TODAY:\n\n"
                for r in top10:
                    context += (f"{r['Rank']}. {r['Player']} ({r['Team']}) — "
                               f"Tier {r['Tier']}, Score {r['Score']}, "
                               f"L10 {r['L10 Hit%']}, L15 {r['L15 Hit%']}, "
                               f"avg {r['Avg H']} hits, batting {r['Order']}, "
                               f"trend {r['Trend']}, vs {r['vs Pitcher']}\n")

                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1200,
                    system=MASTER_SYSTEM_PROMPT,
                    messages=[{
                        "role": "user",
                        "content": (
                            f"{context}\n\n"
                            "These are batters ranked by a hit-props model using "
                            "L10/L15 hit rates, recent form, batting order, and weather. "
                            "Give me your top 3 hit plays (1+ hits) from this list. "
                            "For each: state the case, the counter-case, and a "
                            "confidence range. Be honest — if the sample is thin or "
                            "the pitcher matchup is tough, say so. End with which "
                            "single play you'd bet first."
                        )
                    }]
                )
                st.markdown(response.content[0].text)
            except Exception as e:
                st.error(f"Claude analysis failed: {e}")
