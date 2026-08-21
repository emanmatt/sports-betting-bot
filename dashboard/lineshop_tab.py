"""
dashboard/lineshop_tab.py

The "Line Shop" tab — Outlier-style line comparison:
  - Best line + odds across all books (FanDuel, DK, BetMGM, etc.)
  - Alternate lines for each prop
  - DFS comparison (PrizePicks/Underdog vs sportsbook consensus)
  - L10 hit rate and projection per player

This is a live tab — pulls fresh data when you click a button
(to control OddsAPI credit usage).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from config.settings import SUPPORTED_SPORTS


def render_lineshop_tab(selected_sport: str):
    st.subheader("🛒 Line Shop — Best Lines Across All Books")
    st.caption("Compare FanDuel, DraftKings, BetMGM, Caesars + more. "
               "Find the best number and see DFS edges vs PrizePicks/Underdog.")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"Pulls live props for **{selected_sport}** across all books. "
                    "Uses OddsAPI credits — click when ready.")
    with col2:
        fetch = st.button("🔄 Fetch Lines", type="primary", use_container_width=True)

    if fetch:
        with st.spinner("Fetching props across all books..."):
            try:
                from data_ingestion.official.multibook_engine import MultiBookEngine
                engine = MultiBookEngine()
                props = engine.fetch_multibook_props(selected_sport)
                st.session_state["multibook_props"] = props
                st.session_state["multibook_sport"] = selected_sport
                st.success(f"Loaded {len(props)} props across all books!")
            except Exception as e:
                st.error(f"Failed to fetch: {e}")

        # Also fetch DFS edges
        with st.spinner("Comparing to PrizePicks and Underdog..."):
            try:
                from data_ingestion.dfs.dfs_engine import DFSEngine
                dfs = DFSEngine()
                props = st.session_state.get("multibook_props", [])
                dfs_edges = dfs.find_dfs_edges(selected_sport, props)
                st.session_state["dfs_edges"] = dfs_edges
                if dfs_edges:
                    st.success(f"Found {len(dfs_edges)} DFS edges!")
            except Exception as e:
                st.warning(f"DFS comparison unavailable: {e}")

    props = st.session_state.get("multibook_props", [])
    dfs_edges = st.session_state.get("dfs_edges", [])

    if not props:
        st.info("Click 'Fetch Lines' to load props across all books.")
        st.markdown("""
        **What this shows:**
        - Every book's line for each prop, side by side
        - The single best number available (and which book has it)
        - Alternate lines (e.g. 25.5, 27.5, 29.5)
        - PrizePicks/Underdog lines vs the sportsbook consensus
        - L10 hit rate and a projection for each player
        """)
        return

    # ── DFS Edges section (top priority display) ──────────────────────
    if dfs_edges:
        st.markdown("### 🎯 DFS Edges (PrizePicks / Underdog vs Market)")
        st.caption("When a DFS app's line differs from the sportsbook consensus, "
                   "that's a potential edge.")

        for edge in dfs_edges[:10]:
            direction_emoji = "📈" if edge.edge_direction == "over" else "📉"
            with st.container():
                st.markdown(
                    f"<div style='background:#0d2618;border-left:4px solid #4CAF50;"
                    f"border-radius:8px;padding:12px;margin:6px 0'>"
                    f"{direction_emoji} <b>{edge.player_name}</b> — {edge.stat_label}<br>"
                    f"<b>{edge.app.title()}:</b> {edge.line} | "
                    f"<b>Market consensus:</b> {edge.market_line} | "
                    f"<b>Edge:</b> {edge.edge:+.1f} ({edge.edge_pct}%)<br>"
                    f"<span style='color:#4CAF50'>Play: {edge.edge_direction.upper()} "
                    f"{edge.line} on {edge.app.title()}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )
        st.divider()

    # ── Multi-book props with expandable detail ───────────────────────
    st.markdown("### 📊 All Props — Line Comparison")

    # Filter
    prop_types = sorted(set(p.prop_label for p in props))
    selected_type = st.selectbox("Prop Type", ["All"] + prop_types)

    filtered = props if selected_type == "All" else \
               [p for p in props if p.prop_label == selected_type]

    st.caption(f"{len(filtered)} props")

    # Lazy-load hit rate calculator
    hit_calc = None
    try:
        from analysis.hit_rate import HitRateCalculator
        hit_calc = HitRateCalculator()
    except Exception:
        pass

    for prop in filtered[:40]:  # Cap display
        # Build the header with best lines
        best_over = f"{prop.best_over_line} ({prop.best_over_odds:+d} @ {prop.best_over_book})" \
                    if prop.best_over_line is not None and prop.best_over_odds is not None else "N/A"

        with st.expander(
            f"{prop.player_name} — {prop.prop_label} | "
            f"Consensus: {prop.consensus_line} | "
            f"Best Over: {best_over}"
        ):
            c1, c2 = st.columns([3, 2])

            with c1:
                st.markdown("**📖 Every Book's Line**")
                if prop.book_lines:
                    rows = []
                    for bl in prop.book_lines:
                        rows.append({
                            "Book": bl.sportsbook.upper(),
                            "Line": bl.line,
                            "Over": f"{bl.over_odds:+d}" if bl.over_odds else "–",
                            "Under": f"{bl.under_odds:+d}" if bl.under_odds else "–",
                        })
                    df = pd.DataFrame(rows).sort_values("Line")
                    st.dataframe(df, hide_index=True, use_container_width=True)

                # Best numbers
                if prop.best_over_line is not None:
                    st.markdown(f"✅ **Best OVER:** {prop.best_over_line} "
                               f"({prop.best_over_odds:+d}) @ **{prop.best_over_book.upper()}**")
                if prop.best_under_line is not None:
                    st.markdown(f"✅ **Best UNDER:** {prop.best_under_line} "
                               f"({prop.best_under_odds:+d}) @ **{prop.best_under_book.upper()}**")

                # Alternate lines
                if prop.alt_lines:
                    st.markdown("**🔀 Alternate Lines**")
                    alt_rows = []
                    for line_val in sorted(prop.alt_lines.keys()):
                        books = prop.alt_lines[line_val]
                        best_alt = max(books, key=lambda x: x.over_odds or -1000)
                        alt_rows.append({
                            "Line": line_val,
                            "Best Over": f"{best_alt.over_odds:+d}" if best_alt.over_odds else "–",
                            "Book": best_alt.sportsbook.upper(),
                        })
                    st.dataframe(pd.DataFrame(alt_rows), hide_index=True,
                                use_container_width=True)

            with c2:
                st.markdown("**📈 Hit Rate & Projection**")
                # Projection from model
                try:
                    from analysis.projections import ProjectionModel
                    pm = ProjectionModel()
                    pdata = pm.project_prop(
                        prop.player_name, prop.sport,
                        prop.prop_type, prop.consensus_line or 0,
                        opponent=prop.away_team
                    )
                    pm.close()
                    if pdata["has_data"]:
                        lean_emoji = {"over": "📈", "under": "📉",
                                     "pass": "➖"}.get(pdata["lean"], "")
                        proj_delta = None
                        if prop.consensus_line and pdata["projection"]:
                            proj_delta = f"{pdata['edge']:+.1f} vs line"
                        st.metric("Projection", pdata["projection"], delta=proj_delta)
                        if pdata["lean"] and pdata["lean"] != "pass":
                            st.markdown(f"**Model lean:** {lean_emoji} "
                                       f"{pdata['lean'].upper()} "
                                       f"({pdata['confidence']} confidence)")
                except Exception:
                    pass

                if hit_calc and prop.consensus_line:
                    try:
                        hr = hit_calc.enrich_prop(
                            prop.player_name, prop.sport,
                            prop.prop_type, prop.consensus_line
                        )
                        if hr["has_data"]:
                            st.metric("L10 Hit Rate", f"{hr['l10_rate']}%",
                                     delta=hr["l10_display"])
                            st.metric("L5 Hit Rate", f"{hr['l5_rate']}%")
                            if hr["projection"]:
                                proj_delta = None
                                if prop.consensus_line:
                                    diff = hr["projection"] - prop.consensus_line
                                    proj_delta = f"{diff:+.1f} vs line"
                                st.metric("Projection", hr["projection"],
                                         delta=proj_delta)
                            if hr["trend"]:
                                trend_emoji = {"hot": "🔥", "cold": "🧊",
                                              "stable": "➡️"}.get(hr["trend"], "")
                                st.markdown(f"**Trend:** {trend_emoji} {hr['trend'].title()}")
                            if hr["game_log"]:
                                st.caption(f"Last games: {hr['game_log'][:8]}")
                        else:
                            st.caption("No game history in database yet")
                    except Exception as e:
                        st.caption(f"Hit rate unavailable")
                else:
                    st.caption("Hit rate data loading...")

                # Line shopping value
                try:
                    from data_ingestion.official.multibook_engine import MultiBookEngine
                    eng = MultiBookEngine()
                    shop = eng.get_line_shopping_summary(prop)
                    if shop.get("has_shopping_edge"):
                        st.warning(f"⚡ Line spread: {shop['line_spread']} "
                                  f"across {shop['num_books']} books — shop for value!")
                except Exception:
                    pass

    if hit_calc:
        hit_calc.close()
