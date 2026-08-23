"""Line movement, confidence and correlation utilities."""
from analysis.prop_model import expected_value

def summarize_movement(snapshots):
    if len(snapshots) < 2: return {"movement": 0.0, "velocity": 0.0, "signal": "insufficient_history"}
    ordered = sorted(snapshots, key=lambda x: x["captured_at"])
    movement = float(ordered[-1]["line"] - ordered[0]["line"])
    return {"movement": round(movement, 2), "velocity": round(movement / max(1, len(ordered)-1), 2),
            "signal": "significant" if abs(movement) >= 1.0 else "stable"}

def edge_score(model_probability, market_probability, evidence_quality, sample_size, contradiction_rate=0):
    raw_edge = model_probability - market_probability
    sample_factor = min(1.0, sample_size / 20)
    confidence = max(0.0, min(1.0, (abs(raw_edge) * 6 + evidence_quality * .35 + sample_factor * .3 - contradiction_rate * .4)))
    return {"edge": round(raw_edge, 4), "confidence": round(confidence * 10, 2),
            "recommended": raw_edge > .025 and confidence >= .55}

def parlay_probability(leg_probabilities, pairwise_correlation=0.0):
    independent = 1.0
    for probability in leg_probabilities: independent *= probability
    adjustment = 1 + pairwise_correlation * (len(leg_probabilities) - 1)
    return max(0.0, min(1.0, independent * adjustment))
