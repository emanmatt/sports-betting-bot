"""
dashboard/parlay_tab.py

The 🎰 Parlay Builder tab — builds optimal 2/3/4-leg parlays from
the ranked board, with honest combined probability and correlation
awareness (same-game stacks vs cross-game, clearly labeled).

Requires a ranked board first (from Top Props). Uses the model's
hit rates; real sportsbook lines/odds layer in once OddsAPI credits
return (Sept 1).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st


def _render_parlay_card(parlay, idx):
    """Render one parlay as a styled card."""
    prob_pct = round(parlay.combined_prob * 100)
    # Color by probability
    if prob_pct >= 45:
        color = "#4CAF50"
    elif prob_pct >= 30:
        color = "#ff9800"
    else:
        color = "#f44336"

    type_badge = ("🔗 Same-Game" if parlay.parlay_type == "same-game"
                 else "🌐 Cross-Game")
    corr_badge = {
        "positive": "🟢 Positively correlated (legs tend to hit together)",
        "negative": "🔴 Negatively correlated (legs can miss together)",
        "neutral": "⚪ Independent legs",
    }.get(parlay.correlation, "")

    legs_html = ""
    for leg in parlay.legs:
        p = round(leg.hit_prob * 100)
        legs_html += (f"<div style='padding:4px 0'>"
                     f"• <b>{leg.player_name}</b> {leg.prop_label} "
                     f"<span style='color:#888'>({leg.team}) — {p}%</span></div>")

    st.markdown(
        f"<div style='background:#1c2333;border-left:4px solid {color};"
        f"border-radius:8px;padding:14px;margin:8px 0'>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<b>{parlay.num_legs}-Leg {type_badge}</b>"
        f"<span style='color:{color};font-size:20px;font-weight:bold'>"
        f"{prob_pct}% </span></div>"
        f"<div style='color:#888;font-size:13px;margin:4px 0'>"
        f"Fair odds: {parlay.fair_odds} · Avg tier: {parlay.avg_tier} · {corr_badge}</div>"
        f"<hr style='border-color:#333;margin:8px 0'>"
        f"{legs_html}"
        + (f"<div style='color:#ff9800;font-size:12px;margin-top:8px'>"
           f"{parlay.warning}</div>" if parlay.warning else "")
        + "</div>",
        unsafe_allow_html=True
    )


def render_parlay_tab():
    st.subheader("🎰 Parlay Builder")
    st.caption("Builds the best parlay combinations from your ranked board. "
               "Shows HONEST combined probability — no hiding the real odds. "
               "Same-game stacks and cross-game parlays clearly labeled.")

    props = st.session_state.get("prop_ranks", [])

    if not props:
        st.info("No ranked board loaded yet. Go to **🔥 Top Props**, click "
               "'Rank All Props', then come back here to build parlays.")
        st.markdown("""
        **How this builder is different from just stacking high scores:**
        - **Honest probability** — three 75% legs = ~42%, and it shows you that
        - **Correlation aware** — warns when same-game hitters could all miss
          together, flags when a pitcher's own props hit together
        - **All sizes** — compares 2, 3, and 4-leg options side by side
        - **Both types** — 🔗 same-game stacks and 🌐 cross-game, labeled

        ⚠️ Real sportsbook lines + odds need OddsAPI credits (back Sept 1).
        Until then this uses your model's hit rates for probability.
        """)
        return

    # Reminder about lineup status
    meta = st.session_state.get("lineups_meta", [])
    projected = sum(1 for m in meta if not m.get("confirmed"))
    if projected:
        st.warning(f"⚠️ {projected} game(s) have projected (not confirmed) lineups. "
                  "Parlays with those batters carry lineup risk — a player might "
                  "not start. Confirm lineups before betting.")

    # Build parlays
    with st.spinner("Building optimal parlays..."):
        try:
            from analysis.parlay_builder import ParlayBuilder
            builder = ParlayBuilder()
            result = builder.best_overall(props)
        except Exception as e:
            st.error(f"Parlay builder failed: {e}")
            return

    highlights = result.get("highlights", {})
    by_size = result.get("by_size", {})

    # ── Highlights ──
    if highlights:
        st.markdown("### ⭐ Top Recommendations")
        if "safest" in highlights:
            st.markdown("**🛡️ Safest Play (highest combined probability):**")
            _render_parlay_card(highlights["safest"], 0)
        if "cross_game" in highlights:
            st.markdown("**🌐 Best Cross-Game (spread the risk):**")
            _render_parlay_card(highlights["cross_game"], 1)
        if "correlated" in highlights:
            st.markdown("**🔗 Best Correlated Stack (legs hit together):**")
            _render_parlay_card(highlights["correlated"], 2)

    st.divider()

    # ── By size ──
    st.markdown("### 📊 Best Parlays by Size")
    size_tab = st.radio("Number of legs", [2, 3, 4], horizontal=True,
                       format_func=lambda x: f"{x}-Leg")

    parlays = by_size.get(size_tab, [])
    if not parlays:
        st.info(f"No {size_tab}-leg parlays could be built from the current board.")
    else:
        # Filter option
        ptype_filter = st.selectbox("Type", ["All", "Same-Game only", "Cross-Game only"])
        shown = parlays
        if ptype_filter == "Same-Game only":
            shown = [p for p in parlays if p.parlay_type == "same-game"]
        elif ptype_filter == "Cross-Game only":
            shown = [p for p in parlays if p.parlay_type == "cross-game"]

        st.caption(f"Showing top {len(shown[:8])} {size_tab}-leg parlays, "
                  "ranked by combined probability")
        for i, parlay in enumerate(shown[:8]):
            _render_parlay_card(parlay, i)

    # ── Honest math note ──
    st.divider()
    st.info("""
    **📐 The honest math:** each added leg multiplies the risk. A parlay's
    combined probability is (roughly) each leg's probability multiplied
    together. That's why a 4-leg parlay of strong 70% plays still only hits
    ~24% of the time. Parlays pay more because they're harder to win — the
    house edge compounds with each leg. **Single bets and 2-leg parlays are
    where the math is friendliest.** Bet parlays for the upside, but size them
    small and know the real odds — which this builder always shows you.
    """)
