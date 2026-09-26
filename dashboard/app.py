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

t_analysis, t_props, t_calc, t_track = st.tabs([
    "🧠 Game Analysis",
    "🔥 Props",
    "🎰 Calc & Demons",
    "📊 Track Record",
])

# ── 🧠 GAME ANALYSIS (primary) ──
with t_analysis:
    try:
        from dashboard.game_analysis_tab import render_game_analysis_tab
        render_game_analysis_tab()
    except Exception as e:
        st.error(f"Game Analysis error: {e}")

# ── 🔥 PROPS (sport-routed board) ──
with t_props:
    try:
        if selected_sport == "NFL":
            from dashboard.nfl_tab import render_nfl_tab
            render_nfl_tab()
        elif selected_sport == "NBA":
            st.subheader("🏀 NBA Props")
            st.info("The 2026-27 NBA season starts October 20, 2026 — full "
                    "analysis comes online once games begin.")
        else:
            from dashboard.tophits_tab import render_tophits_tab
            render_tophits_tab(selected_sport)
    except Exception as e:
        st.error(f"Props error: {e}")

# ── 🎰 CALC & DEMONS ──
with t_calc:
    try:
        from dashboard.parlay_calc_tab import render_parlay_calc_tab
        render_parlay_calc_tab()
    except Exception as e:
        st.error(f"Calc & Demons error: {e}")

# ── 📊 TRACK RECORD ──
with t_track:
    try:
        from dashboard.track_record_tab import render_track_record_tab
        render_track_record_tab()
    except Exception as e:
        st.error(f"Track Record error: {e}")
