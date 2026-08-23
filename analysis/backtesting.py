"""Post-game settlement and calibration reporting."""
from datetime import datetime
from database.models import get_session, PickOutcome

def settle_pick(pick_id, actual_value):
    db = get_session()
    try:
        pick = db.get(PickOutcome, pick_id)
        if not pick: raise ValueError("pick not found")
        side_over = "over" in pick.selection.lower()
        pick.actual_value = actual_value
        pick.result = "push" if actual_value == pick.line else ("win" if (actual_value > pick.line) == side_over else "loss")
        odds = pick.odds or -110
        payout = odds / 100 if odds > 0 else 100 / abs(odds)
        pick.roi = 0.0 if pick.result == "push" else (payout if pick.result == "win" else -1.0)
        pick.settled_at = datetime.utcnow(); db.commit()
        return pick.result
    finally: db.close()

def performance_report(sport=None):
    db = get_session()
    try:
        query = db.query(PickOutcome).filter(PickOutcome.result.in_(["win", "loss", "push"]))
        if sport: query = query.filter(PickOutcome.sport == sport)
        picks = query.all(); decided = [p for p in picks if p.result != "push"]
        wins = sum(p.result == "win" for p in decided)
        brier = sum((p.projected_probability - (1 if p.result == "win" else 0)) ** 2 for p in decided if p.projected_probability is not None)
        scored = sum(p.projected_probability is not None for p in decided)
        return {"picks": len(picks), "win_rate": round(wins / len(decided), 3) if decided else None,
                "roi_units": round(sum(p.roi or 0 for p in picks), 3), "brier_score": round(brier / scored, 4) if scored else None}
    finally: db.close()
