"""
dashboard/track_record_tab.py

The 📊 Track Record tab — the learning loop's dashboard.
Shows how the board's predictions have actually performed, broken
down by tier and prop type, plus Claude's honest review of what to
trust and what to fade.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd


def render_track_record_tab():
    st.subheader("📊 Track Record — Does the Board Actually Work?")
    st.caption("Every ranked board gets logged, then graded against real results. "
               "This is the learning loop — the system calibrates based on what "
               "actually happened, not what it predicted.")

    col1, col2 = st.columns(2)
    with col1:
        grade_btn = st.button("🔄 Grade Past Predictions", use_container_width=True)
    with col2:
        refresh_btn = st.button("📊 Refresh Stats", use_container_width=True,
                               type="primary")

    if grade_btn:
        with st.spinner("Grading past predictions against real results..."):
            try:
                from analysis.track_record import TrackRecord
                tr = TrackRecord()
                graded = tr.grade_pending()
                tr.close()
                st.success(f"Graded {graded} predictions.")
            except Exception as e:
                st.error(f"Grading failed: {e}")

    # Load stats
    try:
        from analysis.track_record import TrackRecord
        tr = TrackRecord()
        stats = tr.get_stats()
        calibration = tr.get_calibration()
        recent = tr.get_recent_results(30)
        tr.close()
    except Exception as e:
        st.error(f"Couldn't load track record: {e}")
        return

    if stats.get("total", 0) == 0:
        st.info("No graded predictions yet. Here's how the learning loop works:")
        st.markdown("""
        1. **Rank a board** in the Top Props tab — the top plays get logged as
           predictions automatically.
        2. **Wait for games to finish** and game logs to update (run the rebuild
           or let the daily job run).
        3. **Come here and click "Grade Past Predictions"** — the system pulls the
           real results and marks each prediction hit or miss.
        4. **Watch the calibration build** — over time you'll see the true hit rate
           for each tier and prop type, and Claude will tell you what's working.

        The more predictions logged and graded, the smarter the calibration.
        Give it a week or two of daily use to build a meaningful sample.
        """)
        return

    # ── Overall ──
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Graded", stats["total"])
    m2.metric("Overall Hit Rate", f"{stats['overall_rate']}%")
    if stats.get("batter_rate") is not None:
        m3.metric("Batter Props", f"{stats['batter_rate']}%")
    if stats.get("pitcher_rate") is not None:
        m4.metric("Pitcher Props", f"{stats['pitcher_rate']}%")

    # ── By Tier (calibration) ──
    st.divider()
    st.markdown("### 🎯 Accuracy by Tier — Is the Score Calibrated?")
    if stats.get("by_tier"):
        tier_rows = []
        for tier, data in stats["by_tier"].items():
            expected = {"A": 70, "B": 60, "C": 50}.get(tier, 55)
            cal = data["rate"] - expected
            status = ("✅ well-calibrated" if abs(cal) <= 8 else
                     "⚠️ overrated" if cal < 0 else "💎 underrated")
            tier_rows.append({
                "Tier": tier,
                "Predictions": data["total"],
                "Hit Rate": f"{data['rate']}%",
                "Expected": f"~{expected}%",
                "Status": status,
            })
        st.dataframe(pd.DataFrame(tier_rows), hide_index=True,
                    use_container_width=True)
        st.caption("If Tier A is hitting well below ~70%, the model is "
                  "overconfident on its top plays and the threshold needs tightening.")

    # ── By Prop Type ──
    if stats.get("by_prop"):
        st.markdown("### 📈 Accuracy by Prop Type — What Actually Hits?")
        prop_rows = []
        for label, data in stats["by_prop"].items():
            prop_rows.append({
                "Prop Type": label,
                "Predictions": data["total"],
                "Hit Rate": f"{data['rate']}%",
            })
        st.dataframe(pd.DataFrame(prop_rows), hide_index=True,
                    use_container_width=True)
        st.caption("Prop types at the top are the board's strengths. Ones at the "
                  "bottom (below ~50%) are where it's weak — fade those or ignore them.")

    # ── Recent results ──
    if recent:
        st.markdown("### 📋 Recent Graded Predictions")
        rec_rows = []
        for r in recent:
            emoji = "✅" if r["result"] == "hit" else "❌"
            rec_rows.append({
                "Date": r["date"],
                "Player": r["player"],
                "Prop": r["prop"],
                "Tier": r["tier"],
                "Score": r["score"],
                "Actual": r["actual"],
                "Result": f"{emoji} {r['result']}",
            })
        st.dataframe(pd.DataFrame(rec_rows), hide_index=True,
                    use_container_width=True, height=300)

    # ── Claude's Review ──
    st.divider()
    st.markdown("### 🤖 Claude's Review of the Track Record")
    if st.button("Get Claude's Honest Assessment"):
        with st.spinner("Claude analyzing the track record..."):
            try:
                import anthropic
                from config.settings import ANTHROPIC_API_KEY
                from analysis.system_prompt import MASTER_SYSTEM_PROMPT
                client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

                context = f"""TRACK RECORD DATA:
Overall: {stats['total']} predictions graded, {stats['overall_rate']}% hit rate
Batter props: {stats.get('batter_rate')}% | Pitcher props: {stats.get('pitcher_rate')}%

BY TIER:
"""
                for tier, data in stats.get("by_tier", {}).items():
                    context += f"  Tier {tier}: {data['rate']}% ({data['total']} preds)\n"
                context += "\nBY PROP TYPE:\n"
                for label, data in stats.get("by_prop", {}).items():
                    context += f"  {label}: {data['rate']}% ({data['total']} preds)\n"

                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1200,
                    system=MASTER_SYSTEM_PROMPT,
                    messages=[{
                        "role": "user",
                        "content": (
                            f"{context}\n\nThis is the track record of a prop "
                            "ranking model. Give me an honest assessment:\n"
                            "1. Is the tier system calibrated (are A plays actually "
                            "better than B and C)?\n"
                            "2. Which prop types should I trust and which should I "
                            "fade based on this data?\n"
                            "3. What's the sample size caveat — is this enough data "
                            "to conclude anything yet?\n"
                            "Be honest and statistical. If the sample is too small "
                            "to trust, say so clearly."
                        )
                    }]
                )
                st.markdown(response.content[0].text)
            except Exception as e:
                st.error(f"Claude review failed: {e}")
