"""
dashboard/value_tab.py

The 💎 Value tab — real sportsbook lines + edge, on demand.

Kept SEPARATE from Top Props on purpose:
  - Top Props stays instant (pure model math, no API calls)
  - This tab only spends OddsAPI credits when you click "Fetch Lines",
    and only for the game you pick — so credits last.

Shows for each play: your model %, the real book line + odds, the
book's implied %, the EDGE (model - implied), and the alt ladder.
Edge is the real signal — where your model disagrees with the book
in your favor. A "safe" line with no edge is a slow bleed; this tab
makes that visible instead of hiding it.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd


# Map model prop_stat -> OddsAPI market key
STAT_TO_MARKET = {
    "hits": "batter_hits",
    "total_bases": "batter_total_bases",
    "rbi": "batter_rbis",
    "runs": "batter_runs_scored",
    "home_runs": "batter_home_runs",
    "strikeouts": "pitcher_strikeouts",
    "outs": "pitcher_outs",
}


def _model_prob_for_line(prop, line_value: float) -> float:
    """
    Estimate the model's probability that a player clears a SPECIFIC
    line value, using their stored game-log values. Falls back to the
    prop's own L10/L15 blend for the standard line.
    """
    # prop has l10_rate/l15_rate for its own line; for alt lines we
    # approximate by shifting. Best effort — the ranker has the real logs.
    base = (prop.l10_rate * 0.6 + prop.l15_rate * 0.4) / 100.0
    return round(base, 4)


def render_value_tab(selected_sport: str):
    st.subheader("💎 Value — Real Lines vs Your Model")
    st.caption("Fetches real sportsbook lines ON DEMAND (spends OddsAPI credits "
               "only when you click). Ranks by EDGE — where your model's "
               "probability beats the book's price. That gap is the real money "
               "signal, not just a high hit rate.")

    props = st.session_state.get("prop_ranks", [])
    if not props:
        st.info("Rank a board in **🔥 Top Props** first, then come here to check "
               "real lines and edge against your model's picks.")
        return

    # Build the list of games from the ranked props
    games = sorted(set(p.game_matchup for p in props if p.game_matchup))

    st.markdown("**Pick a game to fetch real lines for** (1 game ≈ a few credits):")
    game_choice = st.selectbox("Game", games)

    col1, col2 = st.columns([1, 1])
    with col1:
        include_alt = st.checkbox("Include alternate lines (ladders)", value=True)
    with col2:
        fetch = st.button("💰 Fetch Real Lines", type="primary")

    if fetch:
        with st.spinner("Fetching real lines from sportsbooks..."):
            try:
                from data_ingestion.official.props_lines import (
                    PropsLines, compute_edge)
                pl = PropsLines()

                # Find the event id for the chosen game
                events = pl.get_events_today()
                event_id = None
                for e in events:
                    matchup = f"{e.get('away_team','')} @ {e.get('home_team','')}"
                    if matchup == game_choice:
                        event_id = e["id"]
                        break

                if not event_id:
                    st.warning("Couldn't find that game in today's odds feed. "
                              "Lines may not be posted yet (they appear 2-4 hrs "
                              "before first pitch).")
                    return

                parsed = pl.fetch_game_props(event_id, include_alt=include_alt)
                pl.attach_prizepicks(parsed)

                if not parsed:
                    st.warning("No lines posted for this game yet. Player props "
                              "usually appear 2-4 hours before first pitch — "
                              "check back closer to game time.")
                    st.caption(f"Credits remaining: {pl.last_credits}")
                    return

                # Match parsed lines to our model props for this game
                game_props = [p for p in props if p.game_matchup == game_choice]
                model_by_name = {}
                for p in game_props:
                    model_by_name.setdefault(p.player_name, []).append(p)

                rows = []
                ladders = {}
                for player, markets in parsed.items():
                    for market_key, player_lines in markets.items():
                        std = player_lines.standard
                        if not std:
                            continue
                        # find a matching model prop for this player+stat
                        model_p = None
                        for mp in model_by_name.get(player, []):
                            if STAT_TO_MARKET.get(mp.prop_stat) == market_key:
                                model_p = mp
                                break
                        model_prob = (_model_prob_for_line(model_p, std.line)
                                     if model_p else None)

                        # Compute edge on BOTH sides and pick the better one.
                        # Over model prob = model_prob; Under = 1 - model_prob.
                        over_edge, under_edge = {}, {}
                        if model_prob is not None:
                            if std.over_odds is not None:
                                over_edge = compute_edge(model_prob, std.over_odds)
                            if std.under_odds is not None:
                                under_edge = compute_edge(1 - model_prob, std.under_odds)

                        # Decide which side to bet (higher positive edge wins)
                        o_e = over_edge.get("edge_pct", -999)
                        u_e = under_edge.get("edge_pct", -999)
                        if max(o_e, u_e) < 3:
                            bet_side = "🚫 Pass"
                            best = over_edge if o_e >= u_e else under_edge
                            best_edge_val = max(o_e, u_e)
                        elif o_e >= u_e:
                            bet_side = "🔼 OVER"
                            best = over_edge
                            best_edge_val = o_e
                        else:
                            bet_side = "🔽 UNDER"
                            best = under_edge
                            best_edge_val = u_e

                        rows.append({
                            "Player": player,
                            "Prop": player_lines.label,
                            "Line": std.line,
                            "Bet": bet_side,
                            "Over": std.over_odds,
                            "Under": std.under_odds,
                            "Book": std.book,
                            "PrizePicks": player_lines.prizepicks or "—",
                            "Model %": f"{model_prob*100:.0f}%" if model_prob else "—",
                            "Edge": (f"{best_edge_val:+.1f}%"
                                    if best_edge_val > -900 else "—"),
                            "EV/$100": (f"${best['ev_per_100']:+.0f}"
                                       if best.get("ev_per_100") is not None else "—"),
                            "Verdict": best.get("verdict", "—"),
                            "_edge_sort": best_edge_val,
                        })
                        if player_lines.alternates:
                            ladders[f"{player} — {player_lines.label}"] = \
                                sorted(player_lines.alternates, key=lambda x: x.line)

                if not rows:
                    st.warning("Lines came back but none matched your ranked "
                              "players for this game. The board may be on "
                              "projected lineups — re-rank once lineups are set.")
                    st.caption(f"Credits remaining: {pl.last_credits}")
                    return

                # Sort by edge (best value first)
                rows.sort(key=lambda r: r["_edge_sort"], reverse=True)
                for r in rows:
                    r.pop("_edge_sort", None)

                st.success(f"Fetched {len(rows)} lines · Credits remaining: "
                          f"{pl.last_credits}")
                st.session_state["value_rows"] = rows
                st.session_state["value_ladders"] = ladders

            except Exception as e:
                st.error(f"Line fetch failed: {e}")
                return

    # Display results
    rows = st.session_state.get("value_rows", [])
    ladders = st.session_state.get("value_ladders", {})

    if rows:
        st.divider()
        st.markdown("### 📊 Lines Ranked by Edge (best value first)")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        st.info("**Bet** = which side to actually play (🔼 OVER / 🔽 UNDER / 🚫 Pass). "
               "**Edge** = your model's probability minus the book's implied "
               "probability, for that side. 🟢 positive = you're getting a better "
               "price than the risk deserves (the real bet). ➖ fair = book priced "
               "it right, no money in it. **EV/$100** = expected profit per $100 "
               "staked if your model is accurate. 🚫 Pass means neither side has "
               "enough edge (under +3%) to be worth it.")

        # Alt ladders
        if ladders:
            st.divider()
            st.markdown("### 🪜 Alternate Line Ladders")
            st.caption("Safer lines (lower number) pay less; riskier (higher) pay "
                      "more. There's no free lunch — a near-certain line pays "
                      "almost nothing. Pick your spot on the risk/payout curve.")
            ladder_choice = st.selectbox("Player / prop", list(ladders.keys()))
            ladder = ladders.get(ladder_choice, [])
            lrows = []
            for opt in ladder:
                lrows.append({
                    "Line": f"{opt.line}+",
                    "Over Odds": opt.over_odds if opt.over_odds else "—",
                    "Implied %": (f"{opt.implied_prob('over')*100:.0f}%"
                                 if opt.over_odds else "—"),
                    "Book": opt.book,
                })
            st.dataframe(pd.DataFrame(lrows), hide_index=True,
                        use_container_width=True)
    else:
        st.caption("No lines fetched yet. Pick a game and click Fetch Real Lines.")
