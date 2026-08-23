"""Distributional player-prop model; no external ML service required."""
from dataclasses import dataclass
import math, random
import numpy as np

@dataclass
class MonteCarloResult:
    mean: float; stddev: float; over_probability: float; under_probability: float; simulations: int

def simulate_prop(values, line, adjustments=None, simulations=20000, seed=7):
    """Bootstrap historical outcomes, retaining variance instead of treating an average as certainty."""
    if not values or line is None: raise ValueError("values and line are required")
    adjustments = adjustments or {}
    data = np.asarray(values, dtype=float)
    weights = np.linspace(0.6, 1.4, len(data)); weights /= weights.sum()
    rng = np.random.default_rng(seed)
    samples = rng.choice(data, size=simulations, replace=True, p=weights)
    mean = float(samples.mean()) + sum(adjustments.values())
    # residual noise avoids overstating confidence when logs are flat
    std = max(float(samples.std(ddof=1)) if len(data) > 1 else 0.0, max(0.5, abs(mean) * 0.08))
    draws = rng.normal(mean, std, simulations)
    over = float((draws > line).mean())
    return MonteCarloResult(round(mean, 3), round(std, 3), round(over, 4), round(1-over, 4), simulations)

def american_implied_probability(odds):
    return 100 / (odds + 100) if odds > 0 else abs(odds) / (abs(odds) + 100)

def no_vig_probability(over_odds, under_odds):
    over, under = american_implied_probability(over_odds), american_implied_probability(under_odds)
    return over / (over + under), under / (over + under)

def expected_value(probability, odds):
    payout = odds / 100 if odds > 0 else 100 / abs(odds)
    return probability * payout - (1 - probability)
