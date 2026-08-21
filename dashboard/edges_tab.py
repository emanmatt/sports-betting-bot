"""
dashboard/edges_tab.py

The "Edges" tab — arbitrage, middles, and +EV bets.
Analyzes the multi-book props already fetched in the Line Shop tab
(so it uses NO extra API credits — pure computation).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st


def render_edges_tab(selected_sport: str):
    st.subheader("💰 Edges — Arbitrage, Middles & +EV")
    st.caption("Analyzes lines already fetched in the Line Shop tab. "
               "No extra API credits used — pure math on the data.")

    props = st.session_state.get("multibook_props", [])

    if not props:
        st.info("No line data loaded yet. Go to the **🛒 Line Shop** tab first "
               "and click 'Fetch Lines', then come back here.")
        st.markdown("""
        **What this finds:**

        **🟢 Arbitrage** — when two books disagree enough that betting BOTH sides
        guarantees a profit no matter the outcome. Rare but risk-free.

        **🎯 Middles** — when the over line at one book is lower than the under line
        at another. If the result lands in the gap, BOTH bets win.

        **📈 Positive EV** — when our projection model strongly disagrees with the
        market line, flagging a bet with positive expected value over time.
        """)
        return

    # Run detectors
    with st.spinner("Scanning for edges..."):
        try:
            from analysis.projections import ArbitrageDetector, ProjectionModel
            detector = ArbitrageDetector()
            arbs = detector.find_arbitrage(props)

            proj_model = ProjectionModel()
            ev_bets = detector.find_positive_ev(props, proj_model, selected_sport)
            proj_model.close()
        except Exception as e:
            st.error(f"Edge detection failed: {e}")
            return

    # Summary
    arb_count = sum(1 for a in arbs if a.arb_type == "arbitrage")
    middle_count = sum(1 for a in arbs if a.arb_type == "middle")

    m1, m2, m3 = st.columns(3)
    m1.metric("🟢 Arbitrage", arb_count)
    m2.metric("🎯 Middles", middle_count)
    m3.metric("📈 +EV Bets", len(ev_bets))

    st.divider()

    # ── Arbitrage ──────────────────────────────────────────────────────
    true_arbs = [a for a in arbs if a.arb_type == "arbitrage"]
    if true_arbs:
        st.markdown("### 🟢 Guaranteed Arbitrage")
        for arb in true_arbs:
            st.markdown(
                f"<div style='background:#0d2618;border-left:4px solid #4CAF50;"
                f"border-radius:8px;padding:12px;margin:6px 0'>"
                f"<b>{arb.player_name}</b> — {arb.prop_label}<br>"
                f"<span style='color:#4CAF50;font-size:18px'>"
                f"💰 {arb.profit_pct}% guaranteed profit</span><br>"
                f"OVER {arb.over_line} ({arb.over_odds:+d}) @ <b>{arb.over_book.upper()}</b><br>"
                f"UNDER {arb.under_line} ({arb.under_odds:+d}) @ <b>{arb.under_book.upper()}</b>"
                f"</div>",
                unsafe_allow_html=True
            )

    # ── Middles ────────────────────────────────────────────────────────
    middles = [a for a in arbs if a.arb_type == "middle"]
    if middles:
        st.markdown("### 🎯 Middle Opportunities")
        st.caption("Bet both sides. If the result lands in the gap, both bets win.")
        for mid in middles[:15]:
            st.markdown(
                f"<div style='background:#1a2332;border-left:4px solid #2196F3;"
                f"border-radius:8px;padding:12px;margin:6px 0'>"
                f"<b>{mid.player_name}</b> — {mid.prop_label} "
                f"<span style='color:#2196F3'>({mid.middle_gap} pt gap)</span><br>"
                f"OVER {mid.over_line} ({mid.over_odds:+d}) @ <b>{mid.over_book.upper()}</b><br>"
                f"UNDER {mid.under_line} ({mid.under_odds:+d}) @ <b>{mid.under_book.upper()}</b><br>"
                f"<span style='color:#888'>Both win if result is between "
                f"{mid.over_line} and {mid.under_line}</span>"
                f"</div>",
                unsafe_allow_html=True
            )

    # ── Positive EV ────────────────────────────────────────────────────
    if ev_bets:
        st.markdown("### 📈 Positive EV Bets")
        st.caption("Our projection model disagrees with the market — these have "
                   "positive expected value over time (not guaranteed per-bet).")
        for ev in ev_bets[:15]:
            edge_color = "#4CAF50" if ev["side"] == "OVER" else "#f44336"
            st.markdown(
                f"<div style='background:#1c2333;border-left:4px solid {edge_color};"
                f"border-radius:8px;padding:12px;margin:6px 0'>"
                f"<b>{ev['player']}</b> — {ev['prop']} "
                f"<span style='color:{edge_color}'>{ev['side']} {ev['line']}</span><br>"
                f"Best odds: {ev['odds']:+d} @ <b>{ev['book'].upper()}</b><br>"
                f"Our projection: <b>{ev['projection']}</b> "
                f"(edge: {ev['edge']:+.1f}) | Confidence: {ev['confidence']}"
                f"</div>",
                unsafe_allow_html=True
            )

    if not true_arbs and not middles and not ev_bets:
        st.info("No edges found in the current lines. This is normal — true edges "
               "are rare. Try fetching fresh lines closer to game time when books "
               "are more likely to disagree.")
