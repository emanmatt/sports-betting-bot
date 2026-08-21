"""
dashboard/claude_tab.py
Claude integration for the dashboard.
- Auto-analyzes today's games using live database data
- Chat interface for asking questions about games/props/news
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
import streamlit as st
from datetime import datetime, timedelta
from database.models import (
    get_session, Game, GameOdds, Team, NewsArticle,
    PropEdgeDB, InjuryReport, BetSignal
)
from config.settings import ANTHROPIC_API_KEY

MODEL = "claude-sonnet-4-6"


def get_live_context(sport: str) -> str:
    """
    Build a comprehensive context string from live database data.
    This is what Claude reads to answer questions about today's games.
    """
    db = get_session()
    try:
        today = datetime.utcnow().date()
        tomorrow = today + timedelta(days=1)

        # Today's games
        games = (db.query(Game)
                 .filter(Game.sport == sport,
                         Game.game_date >= datetime(today.year, today.month, today.day),
                         Game.game_date < datetime(today.year, today.month, today.day + 1))
                 .order_by(Game.game_date)
                 .all())

        lines = [f"=== LIVE DATA FOR {sport} — {today.strftime('%B %d, %Y')} ===\n"]

        # Games and odds
        lines.append("TODAY'S GAMES:")
        for g in games:
            home = db.query(Team).filter_by(team_id=g.home_team_id).first()
            away = db.query(Team).filter_by(team_id=g.away_team_id).first()
            odds = (db.query(GameOdds).filter_by(game_id=g.game_id)
                   .order_by(GameOdds.captured_at.desc()).first())
            opening = (db.query(GameOdds).filter_by(game_id=g.game_id)
                      .order_by(GameOdds.captured_at.asc()).first())

            home_name = home.name if home else "Unknown"
            away_name = away.name if away else "Unknown"
            time_str = g.game_date.strftime("%I:%M %p ET") if g.game_date else "TBD"

            lines.append(f"\n{away_name} @ {home_name} — {time_str}")
            if odds:
                spread_str = f"{odds.spread:+.1f}" if odds.spread is not None else "N/A"
                total_str = str(odds.total_over_under) if odds.total_over_under is not None else "N/A"
                lines.append(f"  Spread: {spread_str} (home) | Total: {total_str}")
                if odds.home_moneyline is not None and odds.away_moneyline is not None:
                    lines.append(f"  ML: Home {odds.home_moneyline:+d} | Away {odds.away_moneyline:+d}")
            if odds and opening and odds.spread is not None and opening.spread is not None:
                move = round(odds.spread - opening.spread, 1)
                if abs(move) >= 0.5:
                    lines.append(f"  ⚡ LINE MOVED: {move:+.1f} from opening")
                    if abs(move) >= 1.5:
                        lines.append(f"  🚨 SHARP MONEY ALERT — significant move")

        # Top prop edges
        props = (db.query(PropEdgeDB)
                .filter(PropEdgeDB.sport == sport,
                        PropEdgeDB.edge_strength >= 3.0)
                .order_by(PropEdgeDB.edge_strength.desc())
                .limit(10)
                .all())

        if props:
            lines.append(f"\nTOP PROP EDGES ({len(props)} found):")
            for p in props:
                lines.append(
                    f"  {p.player_name} | {p.prop_label} {p.edge_direction.upper()} "
                    f"{p.best_over_line} | Strength: {p.edge_strength:.1f}/10 | "
                    f"Best book: {p.best_over_book if p.edge_direction == 'over' else p.best_under_book}"
                )
                if p.player_avg is not None:
                    lines.append(f"    Player avg: {p.player_avg} vs line {p.best_over_line}")
                if p.edge_reason:
                    lines.append(f"    Reason: {p.edge_reason[:100]}")

        # Recent high-impact news
        cutoff = datetime.utcnow() - timedelta(hours=24)
        news = (db.query(NewsArticle)
               .filter(NewsArticle.sport == sport,
                       NewsArticle.published_at >= cutoff,
                       NewsArticle.betting_impact.in_(["high", "medium"]))
               .order_by(NewsArticle.published_at.desc())
               .limit(10)
               .all())

        if news:
            lines.append(f"\nRECENT HIGH-IMPACT NEWS:")
            for n in news:
                impact = "🚨" if n.betting_impact == "high" else "⚠️"
                lines.append(f"  {impact} [{n.source}] {n.title}")

        # Injury reports
        injuries = (db.query(InjuryReport)
                   .filter(InjuryReport.sport == sport,
                           InjuryReport.report_date >= cutoff)
                   .limit(10)
                   .all())

        if injuries:
            lines.append(f"\nINJURY REPORTS:")
            for inj in injuries:
                lines.append(f"  {inj.player_id} | {inj.status} | {inj.injury_type or 'Unknown'}")

        # ── MLB OFFICIAL DATA (lineups, pitchers, weather, fatigue) ──────
        if sport == "MLB":
            try:
                from data_ingestion.official.mlb_client import MLBClient
                from data_ingestion.official.weather_engine import WeatherEngine
                mlb = MLBClient()
                weather = WeatherEngine()

                mlb_games = mlb.get_todays_games()
                if mlb_games:
                    lines.append(f"\n═══ MLB OFFICIAL DATA (Tier 1) ═══")
                    for mg in mlb_games[:6]:
                        lines.append(f"\n{mg.away_team} @ {mg.home_team} — {mg.venue}")
                        # Probable pitchers
                        if mg.away_pitcher:
                            lines.append(f"  {mg.away_team} SP: {mg.away_pitcher}")
                        if mg.home_pitcher:
                            lines.append(f"  {mg.home_team} SP: {mg.home_pitcher}")
                        # Lineup status
                        lineup = mlb.get_lineup(mg.game_pk)
                        if lineup["confirmed"]:
                            lines.append(f"  ✅ Lineups CONFIRMED")
                        else:
                            lines.append(f"  ⏳ Lineups not yet posted")
                        # Weather / wind
                        if mg.venue:
                            wr = weather.get_stadium_weather(mg.venue)
                            if wr.impact_summary:
                                lines.append(f"  🌤️ {wr.impact_summary}")
                                if wr.total_lean and wr.total_lean != "neutral":
                                    lines.append(f"     → Weather favors {wr.total_lean.upper()}")
            except Exception as e:
                lines.append(f"\n[MLB official data unavailable: {e}]")

        # ── REDDIT CHATTER (Tier 3 — soft signals) ──────────────────────
        try:
            from data_ingestion.soft.reddit_client import RedditClient
            reddit = RedditClient()
            chatter = reddit.get_betting_chatter()
            if chatter:
                lines.append(f"\n═══ REDDIT CHATTER (Tier 3 — low weight) ═══")
                for post in chatter[:5]:
                    lines.append(f"  [{post['score']}pts] {post['title'][:100]}")
        except Exception:
            pass

        return "\n".join(lines)

    except Exception as e:
        return f"Error loading context: {e}"
    finally:
        db.close()


def run_auto_analysis(sport: str) -> str:
    """
    Auto-analyze all of today's games for a sport.
    Returns formatted analysis string.
    """
    context = get_live_context(sport)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Using the live sports data below, analyze today's {sport} slate for betting edges.

{context}

Apply the full analysis framework:
- Classify data as Tier 1 (hard facts), Tier 2 (context), Tier 3 (speculation)
- For each game: identify any edge, sharp money signals, and red flags
- For props: flag the strongest edges and why
- Be honest — say NO BET if nothing is actionable
- Use probability ranges, not certainties
- End with a ranked list of today's top 3 plays (or NO BET if nothing qualifies)

Keep it concise and actionable."""

    try:
        from analysis.system_prompt import MASTER_SYSTEM_PROMPT
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=MASTER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        return f"Analysis failed: {e}"


def chat_with_claude(question: str, sport: str, history: list) -> str:
    """
    Answer a user question using live database context.
    """
    context = get_live_context(sport)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build message history
    messages = []
    for msg in history[-6:]:  # Last 6 messages for context
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({
        "role": "user",
        "content": f"""Live {sport} data for today:\n{context}\n\nUser question: {question}"""
    })

    try:
        from analysis.system_prompt import MASTER_SYSTEM_PROMPT
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=MASTER_SYSTEM_PROMPT + "\n\nYou are in a live chat inside the dashboard. Answer the user's question using the live data provided. Keep responses conversational but rigorous — apply the full framework above.",
            messages=messages
        )
        return response.content[0].text
    except Exception as e:
        return f"Error: {e}"


def render_claude_tab(selected_sport: str):
    """Render the full Claude tab in the dashboard."""

    st.subheader("🤖 Claude Analysis")
    st.caption("Claude reads your live database — real odds, props, news, and line movement")

    # Auto-analysis section
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("### 📊 Auto-Analysis")
        st.caption(f"Claude analyzes today's full {selected_sport} slate using live data")
    with col2:
        run_analysis = st.button("▶️ Analyze Today's Games",
                                  use_container_width=True,
                                  type="primary")

    if run_analysis:
        with st.spinner(f"Analyzing today's {selected_sport} games with live data..."):
            analysis = run_auto_analysis(selected_sport)
            st.session_state["auto_analysis"] = analysis
            st.session_state["auto_analysis_sport"] = selected_sport

    if "auto_analysis" in st.session_state:
        sport_label = st.session_state.get("auto_analysis_sport", selected_sport)
        with st.expander(f"📊 {sport_label} Analysis", expanded=True):
            st.markdown(st.session_state["auto_analysis"])

    st.divider()

    # Chat section
    st.markdown("### 💬 Ask Claude")
    st.caption("Ask anything about tonight's games, props, or lines")

    # Example questions
    st.markdown("**Quick questions:**")
    q1, q2, q3, q4 = st.columns(4)
    if q1.button("Best bet tonight?"):
        st.session_state["prefill"] = "What's the best bet tonight based on the data?"
    if q2.button("Sharp money alerts?"):
        st.session_state["prefill"] = "Are there any sharp money line moves I should know about?"
    if q3.button("Best prop edge?"):
        st.session_state["prefill"] = "What's the strongest player prop edge today and why?"
    if q4.button("Any red flags?"):
        st.session_state["prefill"] = "What are the biggest red flags or reasons NOT to bet tonight?"

    # Initialize chat history
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    # Display chat history
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    prefill = st.session_state.pop("prefill", "")
    question = st.chat_input(
        "Ask about tonight's games, props, line movement...",
    ) or prefill

    if question:
        # Show user message
        with st.chat_message("user"):
            st.markdown(question)
        st.session_state["chat_history"].append({
            "role": "user", "content": question
        })

        # Get Claude's response
        with st.chat_message("assistant"):
            with st.spinner("Analyzing live data..."):
                response = chat_with_claude(
                    question,
                    selected_sport,
                    st.session_state["chat_history"]
                )
            st.markdown(response)

        st.session_state["chat_history"].append({
            "role": "assistant", "content": response
        })

    # Clear chat button
    if st.session_state.get("chat_history"):
        if st.button("🗑️ Clear chat"):
            st.session_state["chat_history"] = []
            st.rerun()
