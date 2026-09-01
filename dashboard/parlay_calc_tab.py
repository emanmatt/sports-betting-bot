"""
dashboard/parlay_calc_tab.py

Two tools in one tab:
  1. 🧮 Parlay Calculator — enter stake + target return, get the pick
     combinations that reach it, with honest hit probabilities.
  2. 😈 Demon Slips — high-risk/high-reward long shots surfaced by
     situational factors (injuries, contract years, soft matchups
     stacking together).

Both read the ranked board from Top Props. The calculator uses real
odds if you've fetched them in the Value tab, otherwise model fair odds.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd


def render_parlay_calc_tab():
    st.subheader("🧮 Parlay Calculator & 😈 Demon Slips")

    props = st.session_state.get("prop_ranks", [])
    if not props:
        st.info("Rank a board in **🔥 Top Props** first, then use these tools.")
        return

    tool = st.radio("Tool", ["🧮 Stake → Return Calculator", "😈 Demon Slips"],
                   horizontal=True)

    if tool.startswith("🧮"):
        _render_calculator(props)
    else:
        _render_demons(props)


def _render_calculator(props):
    st.markdown("### 🧮 Enter your stake and the return you want")
    st.caption("It finds the pick combinations whose real payout lands near "
               "your target, ranked by the honest chance they all hit. "
               "Bigger target = lower chance. No high-return, high-probability "
               "parlay exists — this shows you the real tradeoff.")

    c1, c2, c3 = st.columns(3)
    with c1:
        stake = st.number_input("Stake ($)", min_value=1.0, value=20.0, step=5.0)
    with c2:
        target = st.number_input("Target payout ($)", min_value=2.0,
                                 value=100.0, step=10.0)
    with c3:
        max_legs = st.selectbox("Max legs", [2, 3, 4, 5, 6], index=2)

    if stake > 0:
        mult = target / stake
        st.caption(f"That's a **{mult:.1f}x** return "
                  f"(${stake:.0f} → ${target:.0f}, profit ${target-stake:.0f}).")

    # Pull real odds from Value tab if available
    real_lines = {}
    value_rows = st.session_state.get("value_rows", [])
    for r in value_rows:
        side = "over" if "OVER" in r.get("Bet", "") else \
               "under" if "UNDER" in r.get("Bet", "") else None
        if side and r.get("Over") is not None:
            odds = r.get("Over") if side == "over" else r.get("Under")
            try:
                real_lines[(r["Player"], side)] = int(odds)
            except (ValueError, TypeError):
                pass

    if st.button("🔍 Find Parlays", type="primary"):
        from analysis.parlay_calculator import ParlayCalculator
        calc = ParlayCalculator(real_lines=real_lines)
        results = calc.find_parlays(props, stake=stake, target_payout=target,
                                    max_legs=max_legs)

        if not results:
            st.warning(f"No combination of your ranked plays multiplies out to "
                      f"~{target/stake:.1f}x. Try a lower target, more legs, or "
                      f"rank a bigger board. (A very high target may need more "
                      f"legs than the board supports.)")
            return

        src_note = ("real sportsbook odds" if real_lines else
                   "model fair odds — fetch lines in the Value tab for real payouts")
        st.success(f"Found {len(results)} parlays near your target. "
                  f"Odds source: {src_note}.")

        for i, p in enumerate(results[:10], 1):
            prob_pct = round(p.combined_prob * 100)
            color = "#4CAF50" if prob_pct >= 40 else "#ff9800" if prob_pct >= 20 else "#f44336"
            legs_html = ""
            for leg in p.legs:
                side = "🔽U" if leg.side == "under" else "🔼O"
                legs_html += (f"<div style='padding:3px 0'>• <b>{leg.player_name}</b> "
                             f"{side} {leg.prop_label} "
                             f"<span style='color:#888'>({leg.decimal_odds:.2f}x)</span></div>")
            st.markdown(
                f"<div style='background:#1c2333;border-left:4px solid {color};"
                f"border-radius:8px;padding:12px;margin:6px 0'>"
                f"<div style='display:flex;justify-content:space-between'>"
                f"<b>{p.num_legs}-leg parlay</b>"
                f"<span style='color:{color};font-weight:bold'>{prob_pct}% to hit</span>"
                f"</div>"
                f"<div style='color:#4CAF50;font-size:18px;margin:4px 0'>"
                f"${p.stake:.0f} → ${p.payout:.2f} "
                f"<span style='color:#888;font-size:13px'>(profit ${p.profit:.2f})</span>"
                f"</div>{legs_html}</div>",
                unsafe_allow_html=True)

        st.info("**Reality check:** these are sorted by the honest chance all legs "
               "hit. A 3x parlay around 40% still loses more than half the time. "
               "The payout is bigger because it's harder to win — that's how the "
               "house makes money. Bet small, and know the real odds.")


def _render_demons(props):
    st.markdown("### 😈 Demon Slips — High-Risk, High-Reward Long Shots")
    st.caption("These are NOT safe plays. They're ceiling props (home runs, "
               "multi-hit games, big strikeout nights) where situational factors "
               "stack up for an outlier — a hurt teammate opening opportunity, a "
               "soft matchup in a hitter's park, contract-year motivation. Low "
               "chance, big payout. Swing for the fences — and expect to miss most.")

    # Try to pull injuries for the opportunity factor (free MLB data)
    injuries = {}
    try:
        from data_ingestion.official.mlb_client import MLBClient
        mlb = MLBClient()
        raw = mlb.get_injuries() if hasattr(mlb, "get_injuries") else []
        for inj in raw or []:
            team = inj.get("team", "") if isinstance(inj, dict) else ""
            name = inj.get("player", "") if isinstance(inj, dict) else ""
            if team:
                injuries.setdefault(team, []).append(name)
    except Exception:
        pass

    from analysis.demon_slips import DemonSlipBuilder
    builder = DemonSlipBuilder()
    demons = builder.build(props, injuries=injuries)

    if not demons:
        st.info("No demon slips found on the current board. Demons need at least "
               "2 situational factors stacking (soft matchup + hitter park + hot "
               "form, etc.) on a ceiling prop. Rank a fuller board or check closer "
               "to game time when matchups firm up.")
        return

    st.success(f"Found {len(demons)} demon plays (2+ factors stacking).")

    for d in demons[:12]:
        prob_pct = round(d.hit_prob * 100)
        st.markdown(
            f"<div style='background:#2a1c33;border-left:4px solid #b565d8;"
            f"border-radius:8px;padding:12px;margin:6px 0'>"
            f"<div style='display:flex;justify-content:space-between'>"
            f"<b>😈 {d.player_name} — {d.prop_label}</b>"
            f"<span style='color:#b565d8;font-weight:bold'>upside {d.demon_score}</span>"
            f"</div>"
            f"<div style='color:#888;font-size:13px;margin:2px 0'>{d.game_matchup} · "
            f"~{prob_pct}% base rate (long shot)</div>"
            f"<div style='margin-top:6px'>{'  '.join(d.factors)}</div>"
            f"</div>",
            unsafe_allow_html=True)

    st.warning("⚠️ Demon slips are high-variance by design. Most will miss — "
              "that's expected. Only bet what you're fine losing, keep stakes "
              "tiny, and never chase. These are lottery tickets with a slight "
              "edge from the stacked factors, not reliable plays.")
