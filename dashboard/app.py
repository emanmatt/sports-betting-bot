"""
dashboard/app.py

Sports betting research dashboard.
Run with: streamlit run dashboard/app.py

Shows everything in one clean interface:
- Today's games with live odds and line movement
- Player prop edges with book comparison
- AI bet signals with confidence scores
- News feed sorted by impact
- Auto-refreshes every 5 minutes
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database.models import (
    get_session, Game, GameOdds, Team, Player,
    NewsArticle, BetSignal, InjuryReport
)
from config.settings import SUPPORTED_SPORTS

# ── Page config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sports Betting Research Dashboard",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: #1c2333;
        border-radius: 10px;
        padding: 15px;
        margin: 5px 0;
        border-left: 4px solid #4CAF50;
    }
    .metric-card.red { border-left-color: #f44336; }
    .metric-card.yellow { border-left-color: #ff9800; }
    .metric-card.blue { border-left-color: #2196F3; }
    .game-card {
        background: #1c2333;
        border-radius: 10px;
        padding: 20px;
        margin: 10px 0;
        border: 1px solid #2d3748;
    }
    .prop-edge {
        background: #1a2332;
        border-radius: 8px;
        padding: 12px;
        margin: 8px 0;
        border-left: 3px solid #4CAF50;
    }
    .prop-edge.under { border-left-color: #f44336; }
    .news-item {
        background: #1c2333;
        border-radius: 8px;
        padding: 10px;
        margin: 5px 0;
    }
    .news-item.high { border-left: 3px solid #f44336; }
    .news-item.medium { border-left: 3px solid #ff9800; }
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: bold;
    }
    .badge-green { background: #1b4332; color: #4CAF50; }
    .badge-red { background: #3b1219; color: #f44336; }
    .badge-yellow { background: #3b2f00; color: #ff9800; }
    .stTabs [data-baseweb="tab"] { font-size: 16px; }
</style>
""", unsafe_allow_html=True)


# ── Helper functions ──────────────────────────────────────────────────

@st.cache_data(ttl=60)  # Cache for 60 seconds
def get_todays_games(sport: str) -> list[dict]:
    """Get today's games with odds from database."""
    db = get_session()
    try:
        today = datetime.utcnow().date()
        tomorrow = today + timedelta(days=1)

        games = (db.query(Game)
                 .filter(Game.sport == sport,
                         Game.game_date >= datetime.combine(today, datetime.min.time()),
                         Game.game_date < datetime.combine(tomorrow, datetime.min.time()))
                 .order_by(Game.game_date)
                 .all())

        result = []
        for game in games:
            # Get teams
            home = db.query(Team).filter_by(team_id=game.home_team_id).first()
            away = db.query(Team).filter_by(team_id=game.away_team_id).first()

            # Get latest odds
            latest_odds = (db.query(GameOdds)
                          .filter_by(game_id=game.game_id)
                          .order_by(GameOdds.captured_at.desc())
                          .first())

            # Get opening odds for line movement
            opening_odds = (db.query(GameOdds)
                           .filter_by(game_id=game.game_id)
                           .order_by(GameOdds.captured_at.asc())
                           .first())

            spread_move = 0
            total_move = 0
            if latest_odds and opening_odds:
                if latest_odds.spread and opening_odds.spread:
                    spread_move = round(latest_odds.spread - opening_odds.spread, 1)
                if latest_odds.total_over_under and opening_odds.total_over_under:
                    total_move = round(
                        latest_odds.total_over_under - opening_odds.total_over_under, 1
                    )

            result.append({
                "game_id":    game.game_id,
                "home_team":  home.name if home else "Unknown",
                "away_team":  away.name if away else "Unknown",
                "home_abbr":  home.abbreviation if home else "?",
                "away_abbr":  away.abbreviation if away else "?",
                "game_time":  game.game_date.strftime("%I:%M %p ET") if game.game_date else "TBD",
                "status":     game.status,
                "spread":     latest_odds.spread if latest_odds else None,
                "total":      latest_odds.total_over_under if latest_odds else None,
                "home_ml":    latest_odds.home_moneyline if latest_odds else None,
                "away_ml":    latest_odds.away_moneyline if latest_odds else None,
                "spread_move": spread_move,
                "total_move":  total_move,
                "sharp_move":  abs(spread_move) >= 1.5 or abs(total_move) >= 2.0,
            })
        return result
    finally:
        db.close()


@st.cache_data(ttl=300)
def get_recent_news(sport: str, hours: int = 48, limit: int = 20) -> list[dict]:
    db = get_session()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        articles = (db.query(NewsArticle)
                   .filter(NewsArticle.sport == sport,
                           NewsArticle.published_at >= cutoff)
                   .order_by(NewsArticle.published_at.desc())
                   .limit(limit)
                   .all())
        return [{
            "title":      a.title,
            "source":     a.source,
            "impact":     a.betting_impact,
            "published":  a.published_at.strftime("%m/%d %I:%M %p") if a.published_at else "",
            "url":        a.url,
            "tags":       a.relevance_tags or [],
        } for a in articles]
    finally:
        db.close()


@st.cache_data(ttl=60)
def get_bet_signals(sport: str, limit: int = 20) -> list[dict]:
    db = get_session()
    try:
        signals = (db.query(BetSignal)
                  .filter(BetSignal.sport == sport)
                  .order_by(BetSignal.generated_at.desc())
                  .limit(limit)
                  .all())
        return [{
            "game_id":    s.game_id,
            "bet_type":   s.bet_type,
            "selection":  s.bet_selection,
            "confidence": s.confidence,
            "units":      s.recommended_units,
            "reasoning":  s.reasoning,
            "red_flags":  s.red_flags or [],
            "result":     s.result,
            "generated":  s.generated_at.strftime("%m/%d %I:%M %p") if s.generated_at else "",
        } for s in signals]
    finally:
        db.close()


@st.cache_data(ttl=300)
def get_database_stats() -> dict:
    db = get_session()
    try:
        from sqlalchemy import func
        return {
            "teams":    db.query(Team).count(),
            "players":  db.query(Player).count(),
            "games":    db.query(Game).count(),
            "odds":     db.query(GameOdds).count(),
            "news":     db.query(NewsArticle).count(),
            "signals":  db.query(BetSignal).count(),
            "injuries": db.query(InjuryReport).count(),
        }
    finally:
        db.close()


def ml_to_pct(ml: int) -> str:
    """Convert American odds to implied probability."""
    if not ml:
        return ""
    if ml > 0:
        pct = 100 / (ml + 100) * 100
    else:
        pct = abs(ml) / (abs(ml) + 100) * 100
    return f"{pct:.0f}%"


def format_ml(ml: int) -> str:
    if not ml:
        return "N/A"
    return f"+{ml}" if ml > 0 else str(ml)


def format_spread(spread: float) -> str:
    if spread is None:
        return "N/A"
    return f"+{spread}" if spread > 0 else str(spread)


def movement_badge(move: float, label: str) -> str:
    if move == 0:
        return f"<span style='color:#888'>{label}: Stable</span>"
    color = "#4CAF50" if move < 0 else "#f44336"
    arrow = "↓" if move < 0 else "↑"
    return f"<span style='color:{color}'>{label}: {move:+.1f} {arrow}</span>"


# ── Sidebar ────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://em-content.zobj.net/source/apple/391/direct-hit_1f3af.png", width=50)
    st.title("Betting Research")
    st.caption(f"Updated: {datetime.now().strftime('%I:%M %p')}")

    # Database stats
    stats = get_database_stats()
    st.markdown("### 📊 Database")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Teams", stats["teams"])
        st.metric("Games", stats["games"])
        st.metric("Signals", stats["signals"])
    with col2:
        st.metric("Players", stats["players"])
        st.metric("Odds", stats["odds"])
        st.metric("News", stats["news"])

    st.divider()

    # Sport filter
    selected_sport = st.selectbox(
        "Sport", SUPPORTED_SPORTS, index=2  # Default to MLB
    )

    # Auto-refresh
    auto_refresh = st.checkbox("Auto-refresh (60s)", value=False)
    if auto_refresh:
        st.caption("Page refreshes every 60 seconds")

    st.divider()

    # Quick actions
    st.markdown("### ⚡ Quick Actions")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if st.button("📰 Run News Analysis", use_container_width=True):
        with st.spinner("Analyzing news..."):
            try:
                from analysis.news_analyzer import NewsAnalyzer
                analyzer = NewsAnalyzer()
                result = analyzer.analyze_news_for_sport(selected_sport)
                st.session_state["news_analysis"] = result
                st.success("Analysis complete!")
            except Exception as e:
                st.error(f"Analysis failed: {e}")

    if st.button("🎯 Run Props Analysis", use_container_width=True):
        with st.spinner("Fetching prop lines..."):
            try:
                from data_ingestion.official.props_engine import PropsEngine
                engine = PropsEngine()
                edges = engine.analyze_props(selected_sport, search_web=False)
                st.session_state["prop_edges"] = edges
                st.success(f"Found {len(edges)} prop edges!")
            except Exception as e:
                st.error(f"Props failed: {e}")


# ── Main content ───────────────────────────────────────────────────────

st.title(f"🎯 {selected_sport} Betting Research")
st.caption(f"Today: {datetime.now().strftime('%A, %B %d %Y')}")

# ── Tabs ────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📅 Today's Games",
    "⚡ Player Props",
    "🎯 AI Signals",
    "📰 News Feed",
    "📈 Line Movement",
])


# ════════════════════════════════════════════════
# TAB 1: TODAY'S GAMES
# ════════════════════════════════════════════════
with tab1:
    games = get_todays_games(selected_sport)

    if not games:
        st.info(f"No {selected_sport} games found for today. "
               f"Make sure the scheduler is running.")
        st.code("python scheduler/scheduler.py")
    else:
        st.subheader(f"{len(games)} Games Today")

        for game in games:
            with st.container():
                # Game header
                col_away, col_vs, col_home = st.columns([5, 1, 5])
                with col_away:
                    st.markdown(f"### {game['away_team']}")
                    if game.get("away_ml"):
                        st.markdown(f"**ML:** {format_ml(game['away_ml'])} "
                                  f"({ml_to_pct(game['away_ml'])})")
                with col_vs:
                    st.markdown("<br><br>**@**", unsafe_allow_html=True)
                with col_home:
                    st.markdown(f"### {game['home_team']}")
                    if game.get("home_ml"):
                        st.markdown(f"**ML:** {format_ml(game['home_ml'])} "
                                  f"({ml_to_pct(game['home_ml'])})")

                # Odds row
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    spread = game.get("spread")
                    st.metric(
                        "Spread (Home)",
                        format_spread(spread) if spread else "N/A",
                        delta=f"{game['spread_move']:+.1f}" if game.get("spread_move") else None,
                        delta_color="inverse"
                    )
                with c2:
                    total = game.get("total")
                    st.metric(
                        "Total (O/U)",
                        str(total) if total else "N/A",
                        delta=f"{game['total_move']:+.1f}" if game.get("total_move") else None,
                    )
                with c3:
                    st.metric("Game Time", game["game_time"])
                with c4:
                    if game.get("sharp_move"):
                        st.markdown("### ⚡ SHARP MOVE")
                        st.caption("Line moved 1.5+ points")
                    else:
                        st.metric("Line Movement", "Stable")

                st.divider()


# ════════════════════════════════════════════════
# TAB 2: PLAYER PROPS
# ════════════════════════════════════════════════
with tab2:
    st.subheader("⚡ Player Prop Edges")
    st.caption("Lines compared across all books. Edge = line doesn't match player history.")

    # Check for cached prop edges
    prop_edges = st.session_state.get("prop_edges", [])

    if not prop_edges:
        st.info("Click '🎯 Run Props Analysis' in the sidebar to fetch today's prop lines.")

        # Show sample structure
        st.markdown("**What this shows:**")
        cols = st.columns(3)
        with cols[0]:
            st.markdown("""
            **Best Line Comparison**
            - Highest over line available
            - Lowest under line available
            - Line spread across books
            """)
        with cols[1]:
            st.markdown("""
            **Player History**
            - Season average for this stat
            - Last 5 game average
            - Historical vs this opponent
            """)
        with cols[2]:
            st.markdown("""
            **Edge Assessment**
            - Direction (over/under)
            - Strength (1-10)
            - Reasoning
            """)
    else:
        # Filter controls
        col_filter1, col_filter2, col_filter3 = st.columns(3)
        with col_filter1:
            min_strength = st.slider("Min Edge Strength", 0.0, 10.0, 3.0)
        with col_filter2:
            direction_filter = st.selectbox("Direction", ["All", "Over", "Under"])
        with col_filter3:
            prop_type_filter = st.selectbox(
                "Prop Type",
                ["All"] + list(set(e.prop_label for e in prop_edges))
            )

        # Apply filters
        filtered = [e for e in prop_edges
                   if e.edge_strength >= min_strength
                   and (direction_filter == "All" or
                        e.edge_direction.lower() == direction_filter.lower())
                   and (prop_type_filter == "All" or
                        e.prop_label == prop_type_filter)]

        st.caption(f"Showing {len(filtered)} edges (of {len(prop_edges)} total)")

        for edge in filtered:
            direction_color = "green" if edge.edge_direction == "over" else "red"
            direction_emoji = "📈" if edge.edge_direction == "over" else "📉"

            with st.expander(
                f"{direction_emoji} {edge.player_name} — "
                f"{edge.prop_label} {edge.edge_direction.upper()} "
                f"{edge.best_over_line} | Strength: {edge.edge_strength:.1f}/10"
            ):
                col_a, col_b, col_c = st.columns(3)

                with col_a:
                    st.markdown("**Best Lines by Book**")
                    if edge.all_lines:
                        lines_df = pd.DataFrame(edge.all_lines)
                        lines_df = lines_df.sort_values("line")
                        st.dataframe(
                            lines_df[["sportsbook", "line", "over_odds", "under_odds"]],
                            hide_index=True,
                            use_container_width=True
                        )
                    # Highlight best numbers
                    st.markdown(
                        f"✅ **Best OVER:** {edge.best_over_line} "
                        f"({format_ml(edge.best_over_odds)}) @ {edge.best_over_book}"
                    )
                    st.markdown(
                        f"✅ **Best UNDER:** {edge.best_under_line} "
                        f"({format_ml(edge.best_under_odds)}) @ {edge.best_under_book}"
                    )
                    if edge.line_spread >= 0.5:
                        st.warning(f"⚡ Line spread: {edge.line_spread} "
                                  f"(books disagree — shop for best number)")

                with col_b:
                    st.markdown("**Player History**")
                    if edge.player_avg:
                        st.metric("Season Avg", edge.player_avg)
                    if edge.recent_avg:
                        st.metric("Last 5 Games Avg", edge.recent_avg)
                    if edge.vs_opponent_avg:
                        st.metric(f"vs {edge.opponent}", edge.vs_opponent_avg)
                    st.markdown(f"**Edge:** {edge.edge_reason}")

                with col_c:
                    st.markdown("**Context**")
                    st.markdown(f"**Team:** {edge.team}")
                    st.markdown(f"**Opponent:** {edge.opponent or 'Unknown'}")
                    st.markdown(
                        f"**Strength:** {'🟢' * int(edge.edge_strength/2)}"
                        f"{'⚪' * (5 - int(edge.edge_strength/2))}"
                    )
                    if edge.web_context:
                        st.markdown("**Auto-researched:**")
                        st.caption(edge.web_context)


# ════════════════════════════════════════════════
# TAB 3: AI SIGNALS
# ════════════════════════════════════════════════
with tab3:
    st.subheader("🎯 AI Bet Signals")

    signals = get_bet_signals(selected_sport)

    if not signals:
        st.info("No AI signals yet. Run analysis from the command line:")
        st.code(f"python analysis/run_analysis.py --sport {selected_sport}")
    else:
        # Summary metrics
        bets = [s for s in signals if s["selection"] != "NO BET"]
        no_bets = len(signals) - len(bets)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Analyzed", len(signals))
        m2.metric("Bets Recommended", len(bets))
        m3.metric("NO BETs", no_bets)
        m4.metric("Avg Confidence",
                 f"{sum(s['confidence'] for s in bets)/len(bets):.1f}/10"
                 if bets else "N/A")

        st.divider()

        for signal in signals:
            is_bet = signal["selection"] != "NO BET"

            with st.expander(
                f"{'✅' if is_bet else '🚫'} {signal['game_id']} — "
                f"{signal['selection']} | Conf: {signal['confidence']:.0f}/10"
                if signal['confidence'] else
                f"{'✅' if is_bet else '🚫'} {signal['game_id']} — {signal['selection']}"
            ):
                if is_bet:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Bet Type", signal["bet_type"].upper())
                    c2.metric("Confidence", f"{signal['confidence']:.0f}/10")
                    c3.metric("Units", signal["units"])

                    st.markdown(f"**Selection:** {signal['selection']}")
                    if signal.get("reasoning"):
                        st.markdown(f"**Reasoning:** {signal['reasoning']}")
                else:
                    st.markdown("### 🚫 NO BET")
                    if signal.get("reasoning"):
                        st.caption(signal["reasoning"])

                if signal.get("red_flags"):
                    st.markdown("**⚠️ Red Flags:**")
                    for flag in signal["red_flags"]:
                        st.markdown(f"- {flag}")

                st.caption(f"Generated: {signal['generated']}")


# ════════════════════════════════════════════════
# TAB 4: NEWS FEED
# ════════════════════════════════════════════════
with tab4:
    st.subheader("📰 News Feed")

    col_hours, col_impact = st.columns(2)
    with col_hours:
        hours = st.selectbox("Time Range", [6, 12, 24, 48], index=3,
                            format_func=lambda x: f"Last {x} hours")
    with col_impact:
        impact_filter = st.selectbox("Impact", ["All", "High", "Medium", "Low"])

    news = get_recent_news(selected_sport, hours=hours)

    if impact_filter != "All":
        news = [n for n in news if n["impact"].lower() == impact_filter.lower()]

    if not news:
        st.info(f"No {selected_sport} news in the last {hours} hours.")
    else:
        # Show AI news analysis if available
        if "news_analysis" in st.session_state:
            with st.expander("🤖 AI Analysis", expanded=True):
                st.markdown(st.session_state["news_analysis"])

        st.markdown(f"**{len(news)} articles**")

        for article in news:
            impact = article["impact"]
            emoji = "🚨" if impact == "high" else "⚠️" if impact == "medium" else "📰"
            color = "#f44336" if impact == "high" else \
                    "#ff9800" if impact == "medium" else "#888"

            st.markdown(
                f"""<div style='background:#1c2333; border-radius:8px; 
                padding:10px; margin:5px 0; 
                border-left:3px solid {color}'>
                {emoji} <strong>{article['title']}</strong><br>
                <span style='color:#888; font-size:12px'>
                {article['source']} · {article['published']}
                </span>
                </div>""",
                unsafe_allow_html=True
            )


# ════════════════════════════════════════════════
# TAB 5: LINE MOVEMENT
# ════════════════════════════════════════════════
with tab5:
    st.subheader("📈 Line Movement Tracker")
    st.caption("Tracks how lines have moved from open — sharp moves (1.5+ pts) signal professional money")

    games = get_todays_games(selected_sport)

    if not games:
        st.info("No games today.")
    else:
        # Line movement table
        movement_data = []
        for game in games:
            spread_move = game.get("spread_move", 0)
            total_move = game.get("total_move", 0)
            is_sharp = abs(spread_move) >= 1.5 or abs(total_move) >= 2.0

            movement_data.append({
                "Game": f"{game['away_team']} @ {game['home_team']}",
                "Time": game["game_time"],
                "Spread": format_spread(game.get("spread")),
                "Spread Move": f"{spread_move:+.1f}" if spread_move != 0 else "–",
                "Total": str(game.get("total", "N/A")),
                "Total Move": f"{total_move:+.1f}" if total_move != 0 else "–",
                "⚡ Sharp?": "YES ⚡" if is_sharp else "No",
            })

        df = pd.DataFrame(movement_data)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

        # Sharp moves highlighted
        sharp_games = [g for g in games if g.get("sharp_move")]
        if sharp_games:
            st.markdown("### ⚡ Sharp Money Alerts")
            for game in sharp_games:
                st.warning(
                    f"**{game['away_team']} @ {game['home_team']}** — "
                    f"Spread moved {game['spread_move']:+.1f} | "
                    f"Total moved {game['total_move']:+.1f}"
                )
        else:
            st.info("No sharp line moves detected today.")

        st.divider()
        st.markdown("### Understanding Line Movement")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **Sharp Money (1.5+ points):**
            - Professional bettors moving the line
            - Opposite of public betting
            - Most reliable signal
            """)
        with col2:
            st.markdown("""
            **Public Money (small moves):**
            - Casual bettors betting favorites
            - Usually fades by game time
            - Less reliable signal
            """)

# ── Auto-refresh ───────────────────────────────────────────────────────
if auto_refresh:
    import time
    time.sleep(60)
    st.cache_data.clear()
    st.rerun()
