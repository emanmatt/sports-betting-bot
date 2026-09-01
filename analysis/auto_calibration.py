"""
analysis/auto_calibration.py

Automatic calibration — the system nudges its own scoring based on how
its past predictions ACTUALLY performed, without you clicking anything.

The honest design principle: LEARN from the track record, but don't
RELY on it. A cold week or a small sample should barely move anything;
only a large, consistent signal should meaningfully adjust the scoring.

How it works:
  - Reads graded predictions from the track record
  - For each prop type and tier, compares actual hit rate vs expected
  - Produces a small MULTIPLIER per prop type (0.85–1.15 range, capped)
  - The multiplier only moves meaningfully once there's real sample size
    (confidence scales with N — 10 graded picks barely moves it, 100+
    moves it fully within the cap)

Guardrails so it doesn't overreact:
  1. Minimum sample: below 15 graded picks for a type, NO adjustment
  2. Confidence weighting: adjustment scales with sqrt(N), so early
     data has muted effect
  3. Hard caps: never adjusts a prop type by more than ±15%
  4. Regression to neutral: always pulled part-way back toward 1.0, so
     it never fully trusts the sample

Result: the picks improve as real evidence accumulates, but a bad run
of variance won't blow up the model.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import math
from loguru import logger

# Expected hit rate by tier (what the score claims)
TIER_EXPECTED = {"A": 0.68, "B": 0.58, "C": 0.48}

# Guardrail constants
MIN_SAMPLE = 15          # below this, no adjustment for a group
MAX_ADJUST = 0.15        # never move a multiplier more than ±15%
FULL_CONFIDENCE_N = 100  # sample size at which we apply near-full adjustment
REGRESSION = 0.6         # keep only 60% of the computed adjustment (temper)


def _confidence(n: int) -> float:
    """
    Confidence factor 0-1 scaling with sample size.
    sqrt-based so it rises fast early then levels — but capped so we
    need real N before trusting it. 15 picks ~0.39, 50 ~0.71, 100 ~1.0.
    """
    if n < MIN_SAMPLE:
        return 0.0
    return min(1.0, math.sqrt(n / FULL_CONFIDENCE_N))


class AutoCalibration:
    """Computes and caches scoring multipliers from the track record."""

    def __init__(self):
        self.prop_multipliers = {}   # prop_label -> multiplier
        self.tier_multipliers = {}   # tier -> multiplier
        self.summary = []            # human-readable notes
        self.total_graded = 0
        self._loaded = False

    def load(self):
        """Read the track record and compute multipliers. Safe if empty."""
        try:
            from analysis.track_record import TrackRecord
            tr = TrackRecord()
            stats = tr.get_stats()
            tr.close()
        except Exception as e:
            logger.debug(f"[AutoCalib] no track record yet: {e}")
            self._loaded = True
            return self

        self.total_graded = stats.get("total", 0)
        if self.total_graded < MIN_SAMPLE:
            # Not enough data overall — run fully neutral
            self.summary.append(
                f"Only {self.total_graded} graded picks — not enough to "
                f"adjust yet (need {MIN_SAMPLE}+). Running neutral.")
            self._loaded = True
            return self

        # By prop type
        for label, data in stats.get("by_prop", {}).items():
            n = data["total"]
            actual = data["rate"] / 100.0
            mult = self._compute_multiplier(actual, expected=0.55, n=n)
            if mult != 1.0:
                self.prop_multipliers[label] = mult
                direction = "up" if mult > 1 else "down"
                self.summary.append(
                    f"{label}: {data['rate']}% over {n} picks → weight {direction} "
                    f"(×{mult:.2f})")

        # By tier
        for tier, data in stats.get("by_tier", {}).items():
            n = data["total"]
            actual = data["rate"] / 100.0
            expected = TIER_EXPECTED.get(tier, 0.55)
            mult = self._compute_multiplier(actual, expected=expected, n=n)
            if mult != 1.0:
                self.tier_multipliers[tier] = mult

        self._loaded = True
        return self

    def _compute_multiplier(self, actual: float, expected: float,
                            n: int) -> float:
        """
        Turn (actual vs expected) into a tempered, sample-weighted,
        capped multiplier.
        """
        conf = _confidence(n)
        if conf == 0.0:
            return 1.0

        # Raw signal: how much better/worse than expected, relative
        # e.g. actual 0.66 vs expected 0.55 = +0.11 → ratio +0.20
        if expected <= 0:
            return 1.0
        rel = (actual - expected) / expected

        # Apply confidence + regression tempering
        adjust = rel * conf * REGRESSION

        # Cap
        adjust = max(-MAX_ADJUST, min(MAX_ADJUST, adjust))
        return round(1.0 + adjust, 3)

    def prop_multiplier(self, prop_label: str) -> float:
        """Multiplier for a prop type's score (1.0 = neutral)."""
        return self.prop_multipliers.get(prop_label, 1.0)

    def tier_multiplier(self, tier: str) -> float:
        return self.tier_multipliers.get(tier, 1.0)

    def is_active(self) -> bool:
        """True if any real adjustment is being applied."""
        return bool(self.prop_multipliers or self.tier_multipliers)
