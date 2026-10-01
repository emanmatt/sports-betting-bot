"""
dashboard/game_analysis_tab.py

Primary view: a Claude-written framework analysis per game — not stat tables.
- Analyze ONE game (fast) or the whole slate.
- 🎯 TD Tracker: play/pace estimate + ranked anytime-TD scorers per game.
- Save analyses AND TD boards to the database (survives reboots).
- Rate saved items 0-5 stars; leaderboards rank the best analyses and the
  best TD boards across every saved game.
Uses the Anthropic key (no OddsAPI credits).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import re
import streamlit as st

SPORT = "NFL"

_SCORER_RE = re.compile(r'^\s*\d+\.\s*(.+?)\s*[—\-]\s*~?(\d+)\s*%', re.U)


def _parse_td_scorers(board, matchup, rating):
    """Fallback for OLD saved boards with no graded picks: parse the numbered
    '1. Player (POS) — ~XX% ...' lines out of the board text."""
    rows = []
    for line in str(board).splitlines():
        m = _SCORER_RE.match(line)
        if not m:
            continue
        who = m.group(1).strip()
        pct = int(m.group(2))
        pos = ""
        pm = re.search(r'\(([^)]+)\)', who)
        if pm:
            pos = pm.group(1)
            who = who[:pm.start()].strip()
        rows.append({"player": who, "pos": pos, "conf": pct, "verdict": "",
                     "reason": "", "matchup": matchup, "rating": rating})
    return rows


def _flatten_td(saved_rows):
    """TD picks across saved boards. Uses graded picks (dicts) when present,
    else falls back to parsing the old board text. Drops Pass."""
    rows = []
    for r in saved_rows:
        items = r.get("edge_plays") or []
        if items and isinstance(items[0], dict):
            for it in items:
                rows.append({
                    "player": it.get("player", ""),
                    "pos": it.get("pos", ""),
                    "verdict": (it.get("verdict", "") or "").title(),
                    "conf": int(it.get("confidence", 0) or 0),
                    "reason": it.get("reason", ""),
                    "matchup": r["matchup"], "rating": r["rating"],
                })
        else:
            rows.extend(_parse_td_scorers(r["writeup"], r["matchup"], r["rating"]))
    return [p for p in rows if str(p.get("verdict", "")).lower() != "pass"]


def _flatten_plays(saved_rows):
    """Flatten every saved analysis's graded plays into one list.
    Handles the new verdict format (dicts) and the old raw format (tuples)."""
    rows = []
    for r in saved_rows:
        for item in (r.get("edge_plays") or []):
            if isinstance(item, dict):
                rows.append({
                    "player": item.get("player", ""),
                    "prop": item.get("prop", ""),
                    "verdict": (item.get("verdict", "") or "").title(),
                    "conf": int(item.get("confidence", 0) or 0),
                    "reason": item.get("reason", ""),
                    "matchup": r["matchup"], "rating": r["rating"],
                })
            else:
                try:
                    name, label, hr, tier = item
                    rows.append({"player": name, "prop": label,
                                 "verdict": f"Tier {tier}",
                                 "conf": int(float(hr)), "reason": "",
                                 "matchup": r["matchup"], "rating": r["rating"]})
                except Exception:
                    continue
    # drop anything the analysis said to pass on
    return [p for p in rows if p["verdict"].lower() != "pass"]


def _plays_caption(plays):
    """Show the analysis's graded plays (Play/Lean) under a fresh analysis."""
    if not plays:
        return
    keep = [p for p in plays if str(p.get("verdict", "")).lower() != "pass"]
    if not keep:
        st.caption("Analysis graded all model plays a Pass for this game.")
        return
    keep.sort(key=lambda x: int(x.get("confidence", 0) or 0), reverse=True)
    st.caption("Graded plays: " + " · ".join(
        f'{p.get("verdict","")} {p["player"]} {p["prop"]} '
        f'({int(p.get("confidence",0) or 0)}%)' for p in keep[:6]))


def _edge_caption(edge_plays):
    if not edge_plays:
        return
    try:
        st.caption("Model edge plays fed to the analysis: " +
                   " · ".join(f"{n} {pl} ({float(hr):.0f}%, {t})"
                              for n, pl, hr, t in edge_plays[:5]))
    except Exception:
        pass


def _stars(n):
    n = int(n or 0)
    return "★" * n + "☆" * (5 - n)


def _fmt_date(d):
    try:
        return d.strftime("%b %d")
    except Exception:
        return ""


def _best_td_line(board):
    """Pull the '**BEST TD BET:** ...' line out of a TD board for the table."""
    for line in str(board).splitlines():
        if "BEST TD BET" in line.upper():
            return line.split(":", 1)[-1].strip().strip("*").strip() or "—"
    return "—"


def _render_saved(rows, set_rating, delete_saved, td=False):
    """Expanders with the full text + rating slider + delete, per saved item."""
    for row in rows:
        rating = int(row.get("rating", 0) or 0)
        with st.expander(f"{_stars(rating)}  {row['matchup']}", expanded=False):
            st.markdown(row["writeup"])
            rc1, rc2, rc3 = st.columns([2, 1, 1])
            with rc1:
                new_rating = st.slider("Rating", 0, 5, rating,
                                       key=f"rate_{row['id']}")
            with rc2:
                if st.button("Save rating", key=f"saverate_{row['id']}"):
                    try:
                        set_rating(row["id"], new_rating)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Rating failed: {e}")
            with rc3:
                if st.button("🗑️ Delete", key=f"del_{row['id']}"):
                    try:
                        delete_saved(row["id"])
                        st.rerun()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")


def render_game_analysis_tab():
    st.subheader("🧠 Game Analysis")
    st.caption("A framework breakdown per game — situational factors, the "
               "team/scheme matchup, counter-case, and confidence — from the "
               "model's edge data + live injury/news search. Plus a 🎯 TD board. "
               "Uses Anthropic credits (not OddsAPI). Rush-yard props are the edge.")

    try:
        from analysis.nfl_ranker import NFLRanker
        ranker = NFLRanker()
        games = ranker.nfl.get_todays_games()
    except Exception as e:
        st.error(f"Couldn't load games: {e}")
        return

    upcoming = [g for g in games
                if ranker.nfl.classify_status(g.status) != "final"]
    if not upcoming:
        st.info("No upcoming games this week.")
        return

    game_by_matchup = {f"{g.away_team} @ {g.home_team}": g for g in upcoming}

    # ---- Analyze controls ----
    st.markdown(f"**{len(upcoming)} games this week.** "
                "Analyze one game (seconds) or the whole slate (~a minute or two).")
    pick = st.selectbox("Pick a game", list(game_by_matchup.keys()))
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    with c1:
        run_one = st.button("⚡ Analyze This Game", type="primary")
    with c2:
        run_td = st.button("🎯 TD Tracker")
    with c3:
        run_all = st.button("🧠 Analyze All")
    with c4:
        if st.button("🗑️ Clear session"):
            st.session_state.pop("game_analyses", None)
            st.session_state.pop("td_boards", None)
            st.rerun()
    st.caption("Tip: run **Analyze This Game** first, then **TD Tracker** — the "
               "TD board folds in the model's volume data for grounded goal-line reads.")

    results = st.session_state.setdefault("game_analyses", {})
    td_boards = st.session_state.setdefault("td_boards", {})

    if run_one:
        from analysis.game_analysis import analyze_nfl_game
        g = game_by_matchup[pick]
        with st.spinner(f"Analyzing {pick}…"):
            try:
                results[pick] = analyze_nfl_game(g, ranker)
            except Exception as e:
                results[pick] = {"matchup": pick,
                                 "writeup": f"Analysis failed: {e}",
                                 "edge_plays": []}
        st.session_state["game_analyses"] = results
        st.rerun()

    if run_td:
        from analysis.td_tracker import project_touchdowns
        g = game_by_matchup[pick]
        existing = results.get(pick, {})
        with st.spinner(f"Projecting touchdowns for {pick} (pulling real TD data)…"):
            try:
                td_boards[pick] = project_touchdowns(
                    g, existing.get("edge_plays"), ranker=ranker)
            except Exception as e:
                td_boards[pick] = {"matchup": pick,
                                   "board": f"TD projection failed: {e}"}
        st.session_state["td_boards"] = td_boards
        st.rerun()

    if run_all and not st.session_state.get("confirm_all"):
        st.session_state["confirm_all"] = True
        st.warning(f"⚠️ Analyze All fires ~{len(game_by_matchup)} games × several "
                   "Claude calls each (a few $ of credits). Click **Analyze All** "
                   "again to confirm.")
        run_all = False

    if run_all:
        st.session_state["confirm_all"] = False
        from analysis.game_analysis import analyze_nfl_game
        prog = st.progress(0)
        items = list(game_by_matchup.items())
        for i, (m, g) in enumerate(items):
            try:
                results[m] = analyze_nfl_game(g, ranker)
            except Exception as e:
                results[m] = {"matchup": m,
                              "writeup": f"Analysis failed: {e}",
                              "edge_plays": []}
            prog.progress((i + 1) / len(items))
        prog.empty()
        st.session_state["game_analyses"] = results
        st.rerun()

    # ---- Saved store (DB) ----
    store_ok = True
    try:
        from analysis.saved_analyses import (save_analysis, list_saved,
                                             set_rating, delete_saved)
    except Exception as e:
        store_ok = False
        st.warning(f"Saved-item store unavailable: {e}")

    # ---- Fresh (unsaved) results this session ----
    if results:
        st.divider()
        st.markdown("### New analyses (this session)")
        for matchup, data in results.items():
            failed = str(data.get("writeup", "")).startswith("Analysis failed")
            with st.expander(f"🏈 {matchup}", expanded=(len(results) == 1)):
                st.markdown(data["writeup"])
                _plays_caption(data.get("plays"))
                tb = td_boards.get(matchup)
                td_failed = tb and str(tb.get("board", "")).startswith("TD projection failed")
                if tb:
                    st.markdown("---")
                    st.markdown("#### 🎯 TD Board")
                    st.markdown(tb["board"])
                if store_ok:
                    sc1, sc2 = st.columns([1, 1])
                    with sc1:
                        if not failed and st.button("💾 Save analysis",
                                                    key=f"save_an_{matchup}"):
                            try:
                                save_analysis(matchup, SPORT, data["writeup"],
                                              data.get("plays", []),
                                              kind="analysis")
                                st.success("Analysis saved — rate it below.")
                            except Exception as e:
                                st.error(f"Save failed: {e}")
                    with sc2:
                        if tb and not td_failed and st.button(
                                "💾 Save TD board", key=f"save_td_{matchup}"):
                            try:
                                save_analysis(matchup, SPORT, tb["board"],
                                              tb.get("td_plays", []), kind="td")
                                st.success("TD board saved — rate it below.")
                            except Exception as e:
                                st.error(f"Save failed: {e}")

    # ---- Standalone TD boards (matchup not analyzed this session) ----
    standalone_td = {m: b for m, b in td_boards.items() if m not in results}
    if standalone_td:
        st.divider()
        st.markdown("### 🎯 TD Boards")
        for m, b in standalone_td.items():
            td_failed = str(b.get("board", "")).startswith("TD projection failed")
            with st.expander(f"🎯 {m}", expanded=(len(standalone_td) == 1)):
                st.markdown(b["board"])
                if store_ok and not td_failed:
                    if st.button("💾 Save TD board", key=f"save_td_solo_{m}"):
                        try:
                            save_analysis(m, SPORT, b["board"],
                                          b.get("td_plays", []), kind="td")
                            st.success("TD board saved — rate it below.")
                        except Exception as e:
                            st.error(f"Save failed: {e}")

    if not store_ok:
        return

    # ---- Leaderboards + saved items ----
    try:
        saved_an = list_saved(SPORT, kind="analysis")
        saved_td = list_saved(SPORT, kind="td")
    except Exception as e:
        st.warning(f"Couldn't load saved items: {e}")
        return

    try:
        import pandas as pd
    except Exception:
        pd = None

    # ---- Saved-data tools ----
    st.divider()
    tcol1, tcol2 = st.columns([1, 1])
    with tcol1:
        regrade = st.button("♻️ Re-grade all saved with latest analysis")
    with tcol2:
        clear_all = st.button("🗑️ Clear ALL saved")

    if clear_all:
        for r in saved_an + saved_td:
            try:
                delete_saved(r["id"])
            except Exception:
                pass
        st.success("Cleared all saved analyses and TD boards.")
        st.rerun()

    if regrade and not st.session_state.get("confirm_regrade"):
        st.session_state["confirm_regrade"] = True
        st.warning(f"⚠️ Re-grade fires Claude calls for {len(saved_an)} analyses + "
                   f"{len(saved_td)} TD boards (a few $ of credits). Click "
                   "**Re-grade all** again to confirm.")
        regrade = False

    if regrade:
        st.session_state["confirm_regrade"] = False
        from analysis.game_analysis import analyze_nfl_game
        from analysis.td_tracker import project_touchdowns
        total = len(saved_an) + len(saved_td)
        done, skipped = 0, 0
        prog = st.progress(0)
        for r in saved_an:
            g = game_by_matchup.get(r["matchup"])
            if g:
                try:
                    data = analyze_nfl_game(g, ranker)
                    save_analysis(r["matchup"], SPORT, data["writeup"],
                                  data.get("plays", []), kind="analysis")
                except Exception:
                    pass
            else:
                skipped += 1
            done += 1
            if total:
                prog.progress(done / total)
        for r in saved_td:
            g = game_by_matchup.get(r["matchup"])
            if g:
                try:
                    tb = project_touchdowns(g, None, ranker=ranker)
                    save_analysis(r["matchup"], SPORT, tb["board"],
                                  tb.get("td_plays", []), kind="td")
                except Exception:
                    pass
            else:
                skipped += 1
            done += 1
            if total:
                prog.progress(done / total)
        prog.empty()
        msg = "Re-graded all saved games with the latest analysis."
        if skipped:
            msg += (f" ({skipped} skipped — not on this week's slate, so no live "
                    "game to re-analyze.)")
        st.success(msg)
        st.rerun()

    # ===== Top plays across saved analyses (analysis-graded) =====
    st.divider()
    st.markdown(f"### 🏆 Top plays — saved analyses ({len(saved_an)} games)")
    st.caption("Ranked by the analysis's own confidence (form + matchup + "
               "injuries), not raw hit rate. Players graded Pass are excluded.")
    plays = _flatten_plays(saved_an)
    plays.sort(key=lambda x: x["conf"], reverse=True)
    if not plays:
        st.info("Save an analysis above to rank its graded plays here.")
    elif pd is not None:
        df = pd.DataFrame([{
            "Rank": i + 1,
            "Player": p["player"],
            "Prop": p["prop"],
            "Verdict": p["verdict"],
            "Confidence": f'{p["conf"]:.0f}%',
            "Matchup": p["matchup"],
            "Rating": _stars(p["rating"]),
        } for i, p in enumerate(plays)])
        st.dataframe(df, hide_index=True, use_container_width=True)
    if saved_an:
        st.caption("Saved analyses — open to read, re-rate, or delete:")
        _render_saved(saved_an, set_rating, delete_saved, td=False)

    # ===== Top TD scorers across saved boards (analysis-graded) =====
    st.divider()
    st.markdown(f"### 🏆 Top TD scorers — saved boards ({len(saved_td)} games)")
    st.caption("Ranked by the board's graded confidence (real TD data + matchup "
               "+ injuries). Players graded Pass are excluded.")
    scorers = _flatten_td(saved_td)
    scorers.sort(key=lambda x: x["conf"], reverse=True)
    if not scorers:
        st.info("Save a TD board above to rank its scorers here.")
    elif pd is not None:
        df = pd.DataFrame([{
            "Rank": i + 1,
            "Player": s["player"] + (f' ({s["pos"]})' if s.get("pos") else ""),
            "Verdict": s.get("verdict", "") or "—",
            "Anytime TD": f'{s["conf"]}%',
            "Matchup": s["matchup"],
            "Rating": _stars(s["rating"]),
        } for i, s in enumerate(scorers)])
        st.dataframe(df, hide_index=True, use_container_width=True)
    if saved_td:
        st.caption("Saved TD boards — open to read, re-rate, or delete:")
        _render_saved(saved_td, set_rating, delete_saved, td=True)
