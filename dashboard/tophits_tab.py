"""
dashboard/tophits_tab.py

The "Top Props" tab — ranks ALL prop types together (hits, total bases,
RBI, home runs, runs, pitcher strikeouts) so you see the single best
play across every prop type. No OddsAPI credits needed.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta


def _format_game_time(iso_time: str) -> str:
    """Convert MLB's UTC ISO time to a readable ET clock time."""
    if not iso_time:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        et = dt.astimezone(timezone(timedelta(hours=-4)))  # EDT
        return et.strftime("%I:%M %p ET").lstrip("0")
    except Exception:
        return "TBD"


def render_tophits_tab(selected_sport: str):
    st.subheader("🔥 Top Props — Every Prop Type Ranked")
    st.caption("Ranks hits, total bases, RBI, home runs, runs, AND pitcher "
               "strikeouts together — strongest play first. Confirmed lineups + "
               "L10/L15 rates + weather + matchup. No betting-line credits needed.")

    if selected_sport != "MLB":
        st.info("Prop ranking is currently MLB-only.")
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("Pulls today's confirmed lineups + probable pitchers and "
                    "ranks every prop type by hit likelihood.")
    with col2:
        run = st.button("🔥 Rank All Props", type="primary",
                       use_container_width=True)

    if run:
        with st.spinner("Pulling lineups, pitchers, weather, and game logs..."):
            try:
                from data_ingestion.official.mlb_client import MLBClient
                from data_ingestion.official.weather_engine import WeatherEngine
                from analysis.prop_ranker import PropRanker

                mlb = MLBClient()
                weather = WeatherEngine()

                games = mlb.get_todays_games()
                lineups_data = []
                weather_by_venue = {}
                skipped_final = 0

                progress = st.progress(0)
                for i, g in enumerate(games):
                    # Classify game status — skip finished games entirely
                    game_status = mlb.classify_status(g.status)
                    if game_status == "final":
                        skipped_final += 1
                        progress.progress((i + 1) / max(len(games), 1))
                        continue

                    lineup = mlb.get_lineup_or_probable(
                        g.game_pk, g.home_team_id, g.away_team_id
                    )
                    if g.venue and g.venue not in weather_by_venue:
                        weather_by_venue[g.venue] = weather.get_stadium_weather(g.venue)

                    lineups_data.append({
                        "game": f"{g.away_team} @ {g.home_team}",
                        "home_team": g.home_team,
                        "away_team": g.away_team,
                        "venue": g.venue,
                        "status": game_status,
                        "status_raw": g.status,
                        "game_time": g.game_time,
                        "home_pitcher": g.home_pitcher,
                        "away_pitcher": g.away_pitcher,
                        "home_pitcher_id": g.home_pitcher_id,
                        "away_pitcher_id": g.away_pitcher_id,
                        "home_lineup": lineup.get("home", []),
                        "away_lineup": lineup.get("away", []),
                        "confirmed": lineup.get("confirmed", False),
                        "projected": lineup.get("projected", False),
                    })
                    progress.progress((i + 1) / max(len(games), 1))
                progress.empty()

                ranker = PropRanker()
                props = ranker.rank_all_props(lineups_data, weather_by_venue)
                rows = ranker.to_table_rows(props, limit=80)
                ranker.close()

                st.session_state["prop_ranks"] = props
                st.session_state["prop_rank_rows"] = rows
                st.session_state["lineups_meta"] = [
                    {
                        "game": l["game"],
                        "time": l.get("game_time", ""),
                        "confirmed": l["confirmed"],
                        "status": l["status"],
                    }
                    for l in lineups_data
                ]

                upcoming = sum(1 for l in lineups_data if l["status"] == "upcoming")
                live = sum(1 for l in lineups_data if l["status"] == "live")
                confirmed = sum(1 for l in lineups_data if l["confirmed"])

                msg = f"Ranked {len(props)} props — {upcoming} upcoming games"
                if live:
                    msg += f", 🔴 {live} LIVE"
                if skipped_final:
                    msg += f" (skipped {skipped_final} finished)"
                st.success(msg)
                projected = sum(1 for l in lineups_data
                               if l.get("projected") and not l["confirmed"])
                if projected:
                    st.info(f"ℹ️ {projected} game(s) don't have official lineups "
                           "posted yet — showing projected batters from the active "
                           "roster. Re-run once lineups drop (1-3 hrs before game) "
                           "for confirmed batting orders.")
                if upcoming == 0 and live == 0:
                    st.warning("⚠️ No upcoming or live games right now — all of "
                              "today's games may be finished. Check back before "
                              "the next slate.")
            except Exception as e:
                st.error(f"Ranking failed: {e}")
                import traceback
                st.caption(traceback.format_exc()[:600])

    rows = st.session_state.get("prop_rank_rows", [])
    props = st.session_state.get("prop_ranks", [])

    if not rows:
        st.info("Click 'Rank All Props' to generate the ranking.")
        st.markdown("""
        **Prop types ranked together:**
        - **Batters:** 1+ Hits, 2+ Hits, 2+ Total Bases, 3+ Total Bases,
          1+ RBI, Home Run, 1+ Runs
        - **Pitchers:** 5+ / 6+ / 7+ Strikeouts

        **Score (0-100):** L10 rate (45%) + L15 rate (20%) + recent form +
        weather + batting order. Tiers: A (70+), B (55+), C (40+), pass (<40).
        """)
        return

    # ── Games status panel — time + lineup confirmation ──
    meta = st.session_state.get("lineups_meta", [])
    if meta:
        with st.expander("🕐 Today's Games — times & lineup status", expanded=True):
            for m in meta:
                time_str = _format_game_time(m.get("time", ""))
                if m["status"] == "live":
                    badge = "🔴 LIVE"
                elif m["confirmed"]:
                    badge = "✅ Lineup confirmed"
                else:
                    badge = "⏳ Lineup not posted yet (projected)"
                st.markdown(f"**{m['game']}** — {time_str} · {badge}")

    # Game filter (full width, on top)
    games_list = sorted(set(r["Game"] for r in rows if r.get("Game")))
    game_filter = st.selectbox("🎮 Game", ["All Games"] + games_list)

    # ── Legend / key ──
    with st.expander("📖 Key — what the columns & symbols mean"):
        st.markdown("""
**Tier** (overall play strength, from the Score)
- **A** = strongest (score 70+) · **B** = solid (55+) · **C** = playable (40+) · **pass** = weak

**Status**
- **Upcoming** = game hasn't started, bettable · **🔴 LIVE** = game in progress

**Rate columns**
- **L10** = % of last 10 games the player went over this prop line
- **L15** = same over last 15 games (bigger sample = more stable)
- **Season** = % over the line all season
- **Avg** = average value of the stat per game (e.g. avg hits, avg outs)

**Trend** (recent form vs season average)
- **🔥** = hot (last 5 games above his norm) · **➡️** = stable · **🧊** = cold

**Matchup** (batters only — quality of the pitcher they face)
- **🟢 Soft** = beatable pitcher, good spot for a hit
- **➖** = average pitcher
- **🔴 Tough** = ace-level pitcher (high K, low ERA) — harder to hit off

**Park** (stadium's effect on offense)
- **🟢** = hitter-friendly park (boosts hits/HRs)
- **➖** = neutral
- **🔴** = pitcher-friendly park (suppresses offense)

**Flags**
- **⚠️ Questionable/Out** = injury concern
- **⚡ Contract year** = added motivation (when data available)

**Score** = 0-100 composite: recent form (~40%) + opposing pitcher (20%) +
park (10%) + batting order + weather + rest, minus penalties for cold streaks,
thin samples, and injuries.
        """)

    # Filters
    f1, f2, f3 = st.columns(3)
    with f1:
        type_filter = st.selectbox("Type", ["All", "Batter", "Pitcher"])
    with f2:
        prop_types = sorted(set(r["Prop"] for r in rows))
        prop_filter = st.selectbox("Prop", ["All"] + prop_types)
    with f3:
        min_tier = st.selectbox("Min Tier", ["All", "A", "B", "C"])

    filtered = rows
    if game_filter != "All Games":
        filtered = [r for r in filtered if r.get("Game") == game_filter]
    if type_filter != "All":
        filtered = [r for r in filtered if r["Type"] == type_filter]
    if prop_filter != "All":
        filtered = [r for r in filtered if r["Prop"] == prop_filter]
    if min_tier != "All":
        tier_order = {"A": 3, "B": 2, "C": 1, "pass": 0}
        min_val = tier_order[min_tier]
        filtered = [r for r in filtered if tier_order.get(r["Tier"], 0) >= min_val]

    # Summary
    tier_a = sum(1 for r in filtered if r["Tier"] == "A")
    tier_b = sum(1 for r in filtered if r["Tier"] == "B")
    m1, m2, m3 = st.columns(3)
    m1.metric("🅰️ Tier A", tier_a)
    m2.metric("🅱️ Tier B", tier_b)
    m3.metric("Showing", len(filtered))

    st.divider()

    # Top 5 highlighted
    st.markdown("### 🏆 Top 5 Props (all types)")
    for r in filtered[:5]:
        tier_color = {"A": "#4CAF50", "B": "#2196F3",
                     "C": "#ff9800"}.get(r["Tier"], "#888")
        st.markdown(
            f"<div style='background:#1c2333;border-left:4px solid {tier_color};"
            f"border-radius:8px;padding:12px;margin:6px 0'>"
            f"<b>#{r['Rank']} {r['Player']}</b> ({r['Team']}) "
            f"<span style='color:{tier_color}'>— {r['Prop']}</span> "
            f"| Tier {r['Tier']} | Score {r['Score']}<br>"
            f"L10: <b>{r['L10']}</b> | L15: {r['L15']} | Season: {r['Season']} | "
            f"Avg: {r['Avg']} {r['Trend']}<br>"
            f"{r['Type']} vs {r['vs']}"
            f"</div>",
            unsafe_allow_html=True
        )

    st.divider()
    st.markdown("### 📊 Full Ranking — All Prop Types")
    df = pd.DataFrame(filtered)
    st.dataframe(df, hide_index=True, use_container_width=True, height=500)

    # ── Reddit chatter check (Tier 3 soft signal) ──
    st.divider()
    st.markdown("### 💬 Social Chatter (Reddit)")
    st.caption("⚠️ Tier 3 soft signal — what bettors are saying. Heavy public "
               "buzz can be a FADE signal, not a follow. Use as context only, "
               "never as your main reason to bet.")
    if st.button("💬 Check Reddit for Top 5 Plays"):
        with st.spinner("Searching Reddit..."):
            try:
                from data_ingestion.soft.reddit_client import RedditClient
                reddit = RedditClient()
                any_found = False
                for r in filtered[:5]:
                    chatter = reddit.search_player_chatter(r["Player"])
                    if chatter:
                        any_found = True
                        st.markdown(f"**{r['Player']}** ({r['Prop']}):")
                        for c in chatter[:3]:
                            st.markdown(f"- [{c['score']}pts, r/{c['sub']}] "
                                       f"{c['title'][:120]}")
                    else:
                        st.markdown(f"**{r['Player']}**: no recent Reddit mentions")
                if not any_found:
                    st.info("No significant Reddit chatter found on the top plays "
                           "right now (or Reddit is rate-limiting). That's normal — "
                           "quiet props are often better than hyped ones.")
            except Exception as e:
                st.warning(f"Reddit check unavailable: {e}")

    # Claude's take
    st.divider()
    if st.button("🤖 Get Claude's Take on Top Plays"):
        with st.spinner("Claude analyzing..."):
            try:
                import anthropic
                from config.settings import ANTHROPIC_API_KEY
                from analysis.system_prompt import MASTER_SYSTEM_PROMPT
                client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

                top15 = filtered[:15]
                context = "TOP RANKED PROPS TODAY (all types):\n\n"
                for r in top15:
                    context += (f"{r['Rank']}. {r['Player']} ({r['Team']}) — "
                               f"{r['Prop']} | Tier {r['Tier']}, Score {r['Score']}, "
                               f"L10 {r['L10']}, L15 {r['L15']}, Season {r['Season']}, "
                               f"avg {r['Avg']}, {r['Type']} vs {r['vs']}\n")

                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1200,
                    system=MASTER_SYSTEM_PROMPT,
                    messages=[{
                        "role": "user",
                        "content": (
                            f"{context}\n\nThese are props ranked by hit rate over "
                            "standard lines. Give your top 3 plays across ALL prop "
                            "types. For each: the case, counter-case, and confidence "
                            "range. Be honest about thin samples or tough matchups. "
                            "End with the single play you'd bet first and why."
                        )
                    }]
                )
                st.markdown(response.content[0].text)
            except Exception as e:
                st.error(f"Claude analysis failed: {e}")
