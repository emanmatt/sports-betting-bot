"""
dashboard/app.py
Sports Betting Research Dashboard — fully automatic.
All data comes from the database — no manual runs needed.
Run: streamlit run dashboard/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database.models import (
    get_session, Game, GameOdds, Team, Player,
    NewsArticle, BetSignal, InjuryReport, PropEdgeDB
)
from config.settings import SUPPORTED_SPORTS

st.set_page_config(
    page_title="Sports Betting Research",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stMetric { background: #1c2333; border-radius: 8px; padding: 10px; }
    .sharp-alert { background: #2d1a00; border-left: 4px solid #ff9800;
                   border-radius: 8px; padding: 12px; margin: 8px 0; }
    .best-prop { background: #0d2618; border-left: 4px solid #4CAF50;
                 border-radius: 8px; padding: 12px; margin: 8px 0; }
    .prop-under { background: #2d0d0d; border-left: 4px solid #f44336;
                  border-radius: 8px; padding: 12px; margin: 8px 0; }
    .news-high { border-left: 4px solid #f44336; padding: 8px;
                 background: #1c2333; border-radius: 4px; margin: 4px 0; }
    .news-med  { border-left: 4px solid #ff9800; padding: 8px;
                 background: #1c2333; border-radius: 4px; margin: 4px 0; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────

def fmt_ml(ml):
    if not ml: return "N/A"
    return f"+{ml}" if ml > 0 else str(ml)

def fmt_spread(s):
    if s is None: return "N/A"
    return f"+{s}" if s > 0 else str(s)

def ml_pct(ml):
    if not ml: return ""
    pct = 100/(ml+100)*100 if ml > 0 else abs(ml)/(abs(ml)+100)*100
    return f"({pct:.0f}%)"


@st.cache_data(ttl=60)
def get_db_stats():
    db = get_session()
    try:
        return {
            "teams":   db.query(Team).count(),
            "players": db.query(Player).count(),
            "games":   db.query(Game).count(),
            "odds":    db.query(GameOdds).count(),
            "news":    db.query(NewsArticle).count(),
            "signals": db.query(BetSignal).count(),
            "props":   db.query(PropEdgeDB).count(),
        }
    finally:
        db.close()


@st.cache_data(ttl=60)
def get_todays_games(sport):
    db = get_session()
    try:
        today = datetime.utcnow().date()
        tomorrow = today + timedelta(days=1)
        games = (db.query(Game)
                 .filter(Game.sport == sport,
                         Game.game_date >= datetime(today.year, today.month, today.day),
                         Game.game_date < datetime(tomorrow.year, tomorrow.month, tomorrow.day))
                 .order_by(Game.game_date)
                 .all())
        result = []
        for g in games:
            home = db.query(Team).filter_by(team_id=g.home_team_id).first()
            away = db.query(Team).filter_by(team_id=g.away_team_id).first()
            latest = (db.query(GameOdds).filter_by(game_id=g.game_id)
                      .order_by(GameOdds.captured_at.desc()).first())
            opening = (db.query(GameOdds).filter_by(game_id=g.game_id)
                       .order_by(GameOdds.captured_at.asc()).first())
            spread_move = total_move = 0
            if latest and opening:
                if latest.spread and opening.spread:
                    spread_move = round(latest.spread - opening.spread, 1)
                if latest.total_over_under and opening.total_over_under:
                    total_move = round(latest.total_over_under - opening.total_over_under, 1)
            result.append({
                "game_id":    g.game_id,
                "home":       home.name if home else g.home_team_id,
                "away":       away.name if away else g.away_team_id,
                "time":       g.game_date.strftime("%I:%M %p ET") if g.game_date else "TBD",
                "spread":     latest.spread if latest else None,
                "total":      latest.total_over_under if latest else None,
                "home_ml":    latest.home_moneyline if latest else None,
                "away_ml":    latest.away_moneyline if latest else None,
                "spread_move": spread_move,
                "total_move":  total_move,
                "sharp_move":  abs(spread_move) >= 1.5 or abs(total_move) >= 2.0,
            })
        return result
    finally:
        db.close()


@st.cache_data(ttl=120)
def get_prop_edges(sport, min_strength=0, direction="All", limit=50):
    db = get_session()
    try:
        q = db.query(PropEdgeDB).filter(PropEdgeDB.sport == sport,
                                         PropEdgeDB.edge_strength >= min_strength)
        if direction != "All":
            q = q.filter(PropEdgeDB.edge_direction == direction.lower())
        edges = q.order_by(PropEdgeDB.edge_strength.desc()).limit(limit).all()
        return edges
    finally:
        db.close()


@st.cache_data(ttl=120)
def get_best_props(limit=10):
    """Get the top prop edges across all sports."""
    db = get_session()
    try:
        return (db.query(PropEdgeDB)
                .filter(PropEdgeDB.edge_strength >= 4.0)
                .order_by(PropEdgeDB.edge_strength.desc())
                .limit(limit)
                .all())
    finally:
        db.close()


@st.cache_data(ttl=300)
def get_news(sport, hours=48, limit=30):
    db = get_session()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return (db.query(NewsArticle)
                .filter(NewsArticle.sport == sport,
                        NewsArticle.published_at >= cutoff)
                .order_by(NewsArticle.published_at.desc())
                .limit(limit)
                .all())
    finally:
        db.close()


@st.cache_data(ttl=60)
def get_signals(sport, limit=20):
    db = get_session()
    try:
        return (db.query(BetSignal)
                .filter(BetSignal.sport == sport)
                .order_by(BetSignal.generated_at.desc())
                .limit(limit)
                .all())
    finally:
        db.close()


def get_cached_ai_analysis(sport):
    """Read cached AI analysis from file."""
    try:
        path = Path(f"analysis_cache/{sport}_analysis.txt")
        if path.exists():
            return path.read_text()
    except Exception:
        pass
    return None


# ── Sidebar ────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🎯 Betting Research")
    st.caption(f"Updated: {datetime.now().strftime('%I:%M %p')}")

    stats = get_db_stats()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Teams",   stats["teams"])
        st.metric("Games",   stats["games"])
        st.metric("Props",   stats["props"])
    with col2:
        st.metric("Players", stats["players"])
        st.metric("Odds",    stats["odds"])
        st.metric("News",    stats["news"])

    st.divider()
    selected_sport = st.selectbox("Sport", SUPPORTED_SPORTS, index=0)

    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.markdown("**Scheduler Status**")
    st.caption("Running on Railway 24/7 ✅")
    st.caption("Props update every 2 hours")
    st.caption("News updates every 30 min")
    st.caption("Odds update every 30 min")


# ── Main tabs ─────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs([
    "📅 Today's Games",
    "🔥 Top Props",
    "⭐ Best Props",
    "🛒 Line Shop",
    "💰 Edges",
    "⚡ All Props",
    "🎯 AI Signals",
    "📰 News",
    "📈 Line Movement",
    "🤖 Claude",
])


# ════════════════════════════════════════════════════════
# TAB 1: TODAY'S GAMES
# ════════════════════════════════════════════════════════
with tab1:
    games = get_todays_games(selected_sport)
    st.subheader(f"{len(games)} {selected_sport} Games Today")

    if not games:
        st.info(f"No {selected_sport} games today. Scheduler is running and will update automatically.")
    else:
        for g in games:
            with st.container():
                c1, mid, c2 = st.columns([5, 1, 5])
                with c1:
                    st.markdown(f"### {g['away']}")
                    st.markdown(f"**ML:** {fmt_ml(g['away_ml'])} {ml_pct(g['away_ml'])}")
                with mid:
                    st.markdown("<br><br>**@**", unsafe_allow_html=True)
                with c2:
                    st.markdown(f"### {g['home']}")
                    st.markdown(f"**ML:** {fmt_ml(g['home_ml'])} {ml_pct(g['home_ml'])}")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Spread", fmt_spread(g["spread"]),
                          delta=f"{g['spread_move']:+.1f}" if g.get("spread_move") else None,
                          delta_color="inverse")
                m2.metric("Total", str(g["total"]) if g["total"] else "N/A",
                          delta=f"{g['total_move']:+.1f}" if g.get("total_move") else None)
                m3.metric("Time", g["time"])
                with m4:
                    if g.get("sharp_move"):
                        st.markdown("### ⚡ SHARP MOVE")
                        st.caption("Line moved 1.5+ pts")
                    else:
                        st.metric("Movement", "Stable")
                st.divider()


# ════════════════════════════════════════════════════════
# TAB 2: TOP HITS (ranked batter hit plays)
# ════════════════════════════════════════════════════════
with tab2:
    try:
        from dashboard.tophits_tab import render_tophits_tab
        render_tophits_tab(selected_sport)
    except Exception as e:
        st.error(f"Top Hits error: {e}")


# ════════════════════════════════════════════════════════
# TAB 3: BEST PROPS (auto-populated from DB)
# ════════════════════════════════════════════════════════
with tab3:
    st.subheader("⭐ Best Player Prop Edges Today")
    st.caption("Automatically updated every 2 hours by the scheduler. No manual action needed.")

    best = get_best_props(limit=15)

    if not best:
        st.info("Props are being analyzed automatically. Check back in a few minutes — the scheduler fetches props every 2 hours.")
        st.markdown("**What this shows when populated:**")
        st.markdown("- Top prop edges across all sports")
        st.markdown("- Line comparison across all books")
        st.markdown("- Player historical averages vs the line")
        st.markdown("- Edge strength score (1-10)")
    else:
        # Summary row
        over_count  = sum(1 for p in best if p.edge_direction == "over")
        under_count = sum(1 for p in best if p.edge_direction == "under")
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Edges", len(best))
        m2.metric("Over Edges",  over_count)
        m3.metric("Under Edges", under_count)
        st.divider()

        for prop in best:
            direction = prop.edge_direction or "none"
            css_class = "best-prop" if direction == "over" else "prop-under"
            emoji = "📈" if direction == "over" else "📉"
            star = "⭐ " if prop.is_best_bet else ""

            with st.expander(
                f"{star}{emoji} {prop.player_name} — "
                f"{prop.prop_label} {direction.upper()} {prop.best_over_line} "
                f"| {prop.sport} | Strength: {prop.edge_strength:.1f}/10",
                expanded=prop.is_best_bet
            ):
                c1, c2, c3 = st.columns(3)

                with c1:
                    st.markdown("**📊 Best Lines by Book**")
                    if prop.all_lines:
                        df = pd.DataFrame(prop.all_lines)
                        if not df.empty:
                            df = df.sort_values("line")
                            st.dataframe(
                                df[["sportsbook","line","over_odds","under_odds"]],
                                hide_index=True,
                                use_container_width=True
                            )
                    st.markdown(f"✅ **Best OVER:** {prop.best_over_line} "
                               f"({fmt_ml(prop.best_over_odds)}) @ {prop.best_over_book}")
                    st.markdown(f"✅ **Best UNDER:** {prop.best_under_line} "
                               f"({fmt_ml(prop.best_under_odds)}) @ {prop.best_under_book}")
                    if prop.line_spread and prop.line_spread >= 0.5:
                        st.warning(f"⚡ Books disagree by {prop.line_spread} — shop for best number")

                with c2:
                    st.markdown("**📈 Player History**")
                    if prop.player_avg:
                        st.metric("Season Avg", prop.player_avg,
                                 delta=f"{prop.player_avg - prop.best_over_line:+.1f} vs line"
                                 if prop.best_over_line else None)
                    if prop.recent_avg:
                        st.metric("Last 5 Avg", prop.recent_avg)
                    if prop.vs_opponent_avg:
                        st.metric(f"vs {prop.opponent}", prop.vs_opponent_avg)
                    if prop.edge_reason:
                        st.caption(prop.edge_reason)

                with c3:
                    st.markdown("**🔍 Context**")
                    st.markdown(f"**Team:** {prop.team or 'N/A'}")
                    st.markdown(f"**Opponent:** {prop.opponent or 'N/A'}")
                    strength_bars = "🟢" * int(prop.edge_strength/2) + "⚪" * (5 - int(prop.edge_strength/2))
                    st.markdown(f"**Edge:** {strength_bars}")
                    if prop.web_context:
                        st.markdown("**Auto-researched:**")
                        st.caption(prop.web_context[:300])
                    st.caption(f"Updated: {prop.generated_at.strftime('%I:%M %p') if prop.generated_at else 'N/A'}")


# ════════════════════════════════════════════════════════
# TAB 4: LINE SHOP (multi-book + DFS)
# ════════════════════════════════════════════════════════
with tab4:
    try:
        from dashboard.lineshop_tab import render_lineshop_tab
        render_lineshop_tab(selected_sport)
    except Exception as e:
        st.error(f"Line Shop error: {e}")


# ════════════════════════════════════════════════════════
# TAB 5: EDGES (arbitrage, middles, +EV)
# ════════════════════════════════════════════════════════
with tab5:
    try:
        from dashboard.edges_tab import render_edges_tab
        render_edges_tab(selected_sport)
    except Exception as e:
        st.error(f"Edges error: {e}")


# ════════════════════════════════════════════════════════
# TAB 6: ALL PROPS with filters
# ════════════════════════════════════════════════════════
with tab6:
    st.subheader(f"⚡ {selected_sport} Player Props")

    f1, f2, f3 = st.columns(3)
    with f1:
        min_str = st.slider("Min Edge Strength", 0.0, 10.0, 2.0)
    with f2:
        dir_filter = st.selectbox("Direction", ["All", "Over", "Under"])
    with f3:
        prop_filter = st.selectbox("Sport", SUPPORTED_SPORTS,
                                   index=SUPPORTED_SPORTS.index(selected_sport))

    edges = get_prop_edges(prop_filter, min_str, dir_filter)

    if not edges:
        st.info(f"No {prop_filter} props found matching filters. "
               f"Props update automatically every 2 hours.")
    else:
        st.caption(f"{len(edges)} edges found")
        for edge in edges:
            direction = edge.edge_direction or "none"
            emoji = "📈" if direction == "over" else "📉"
            with st.expander(
                f"{emoji} {edge.player_name} — {edge.prop_label} "
                f"{direction.upper()} {edge.best_over_line} | "
                f"Strength: {edge.edge_strength:.1f}/10"
            ):
                c1, c2 = st.columns(2)
                with c1:
                    if edge.all_lines:
                        df = pd.DataFrame(edge.all_lines)
                        if not df.empty:
                            st.dataframe(
                                df[["sportsbook","line","over_odds","under_odds"]],
                                hide_index=True, use_container_width=True
                            )
                with c2:
                    st.markdown(f"**Best OVER:** {edge.best_over_line} "
                               f"{fmt_ml(edge.best_over_odds)} @ {edge.best_over_book}")
                    st.markdown(f"**Best UNDER:** {edge.best_under_line} "
                               f"{fmt_ml(edge.best_under_odds)} @ {edge.best_under_book}")
                    if edge.player_avg:
                        st.metric("Player Avg", edge.player_avg)
                    if edge.edge_reason:
                        st.caption(edge.edge_reason)


# ════════════════════════════════════════════════════════
# TAB 7: AI SIGNALS
# ════════════════════════════════════════════════════════
with tab7:
    st.subheader("🎯 AI Bet Signals")

    # Show cached AI news analysis
    ai_analysis = get_cached_ai_analysis(selected_sport)
    if ai_analysis:
        with st.expander("🤖 Latest AI News Analysis", expanded=True):
            st.markdown(ai_analysis)
    else:
        st.info("AI analysis runs automatically every 3 hours. Check back soon.")

    signals = get_signals(selected_sport)
    if signals:
        bets = [s for s in signals if s.bet_selection != "NO BET"]
        m1, m2, m3 = st.columns(3)
        m1.metric("Analyzed", len(signals))
        m2.metric("Bets Found", len(bets))
        m3.metric("NO BETs", len(signals) - len(bets))

        for s in signals:
            is_bet = s.bet_selection != "NO BET"
            icon = "✅" if is_bet else "🚫"
            with st.expander(f"{icon} {s.game_id} — {s.bet_selection}"):
                if is_bet:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Type", s.bet_type.upper() if s.bet_type else "N/A")
                    c2.metric("Confidence", f"{s.confidence:.0f}/10" if s.confidence else "N/A")
                    c3.metric("Units", s.recommended_units)
                    if s.reasoning:
                        st.markdown(f"**Reasoning:** {s.reasoning}")
                else:
                    st.caption(s.reasoning or "Insufficient edge identified")
                if s.red_flags:
                    st.markdown("**⚠️ Red Flags:**")
                    for flag in s.red_flags:
                        st.markdown(f"- {flag}")
    else:
        st.info("AI game signals will appear here as they're generated.")


# ════════════════════════════════════════════════════════
# TAB 8: NEWS FEED
# ════════════════════════════════════════════════════════
with tab8:
    st.subheader("📰 News Feed")

    c1, c2 = st.columns(2)
    with c1:
        hours = st.selectbox("Time Range", [6, 12, 24, 48], index=3,
                            format_func=lambda x: f"Last {x} hours")
    with c2:
        impact = st.selectbox("Impact", ["All", "High", "Medium", "Low"])

    articles = get_news(selected_sport, hours=hours)
    if impact != "All":
        articles = [a for a in articles if a.betting_impact and
                   a.betting_impact.lower() == impact.lower()]

    if not articles:
        st.info(f"No {selected_sport} news in the last {hours} hours.")
    else:
        st.caption(f"{len(articles)} articles")
        for a in articles:
            imp = a.betting_impact or "low"
            color = "#f44336" if imp == "high" else "#ff9800" if imp == "medium" else "#888"
            emoji = "🚨" if imp == "high" else "⚠️" if imp == "medium" else "📰"
            st.markdown(
                f"<div style='background:#1c2333;border-radius:6px;padding:8px;"
                f"margin:4px 0;border-left:3px solid {color}'>"
                f"{emoji} <b>{a.title}</b><br>"
                f"<span style='color:#888;font-size:12px'>"
                f"{a.source} · {a.published_at.strftime('%m/%d %I:%M %p') if a.published_at else ''}"
                f"</span></div>",
                unsafe_allow_html=True
            )


# ════════════════════════════════════════════════════════
# TAB 9: LINE MOVEMENT
# ════════════════════════════════════════════════════════
with tab9:
    st.subheader("📈 Line Movement")
    st.caption("Sharp money = 1.5+ point moves")

    games = get_todays_games(selected_sport)
    if not games:
        st.info("No games today.")
    else:
        data = [{
            "Game":         f"{g['away']} @ {g['home']}",
            "Time":         g["time"],
            "Spread":       fmt_spread(g["spread"]),
            "Spread Move":  f"{g['spread_move']:+.1f}" if g.get("spread_move") else "–",
            "Total":        str(g["total"]) if g["total"] else "N/A",
            "Total Move":   f"{g['total_move']:+.1f}" if g.get("total_move") else "–",
            "Sharp?":       "⚡ YES" if g.get("sharp_move") else "No",
        } for g in games]

        st.dataframe(pd.DataFrame(data), hide_index=True, use_container_width=True)

        sharp = [g for g in games if g.get("sharp_move")]
        if sharp:
            st.markdown("### ⚡ Sharp Money Alerts")
            for g in sharp:
                st.warning(f"**{g['away']} @ {g['home']}** — "
                          f"Spread {g['spread_move']:+.1f} | Total {g['total_move']:+.1f}")

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Sharp Money (1.5+ pts):** Professional bettors — most reliable signal")
        with c2:
            st.markdown("**Public Money (small moves):** Casual bettors — fades by game time")


# ════════════════════════════════════════════════════════
# TAB 7: CLAUDE — Chat + Auto-Analysis
# ════════════════════════════════════════════════════════
with tab10:
    try:
        from dashboard.claude_tab import render_claude_tab
        render_claude_tab(selected_sport)
    except Exception as e:
        st.error(f"Claude tab error: {e}")
        st.info("Make sure your ANTHROPIC_API_KEY is set in Streamlit secrets.")
