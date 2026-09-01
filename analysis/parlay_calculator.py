"""
analysis/parlay_calculator.py

Stake -> Return parlay calculator.

You enter: how much you're staking + the return you want (either a
target $ payout or a target multiplier). It searches combinations of
your ranked plays and returns the parlays whose REAL combined odds land
closest to your target — with the honest hit probability shown for each.

Two modes for the odds:
  - REAL: if you've fetched lines in the Value tab, uses actual book odds
  - MODEL: otherwise, uses fair odds implied by the model's probability
    (labeled clearly, since these have no vig and are optimistic)

Honest framing baked in: the higher the return you want, the lower the
probability. There is no high-return, high-probability parlay — the
calculator shows you the tradeoff instead of hiding it.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from itertools import combinations


def american_to_decimal(odds: int) -> float:
    """Convert American odds to a decimal multiplier."""
    if odds is None:
        return None
    if odds > 0:
        return 1 + odds / 100.0
    else:
        return 1 + 100.0 / -odds


def prob_to_fair_decimal(prob: float) -> float:
    """Fair decimal odds from a probability (no vig)."""
    if prob <= 0:
        return None
    return round(1 / prob, 4)


@dataclass
class CalcLeg:
    player_name: str
    prop_label:  str
    side:        str
    decimal_odds: float
    hit_prob:    float
    odds_source: str          # "real" or "model"
    game_matchup: str = ""


@dataclass
class CalcParlay:
    legs:          list
    num_legs:      int
    combined_decimal: float   # total payout multiplier
    combined_prob: float      # honest probability all hit
    stake:         float
    payout:        float      # stake * combined_decimal
    profit:        float
    odds_source:   str


class ParlayCalculator:
    """Finds parlay combinations that hit a target return."""

    def __init__(self, real_lines: dict = None):
        """
        real_lines: optional {(player, side): american_odds} from Value tab.
        If provided, uses real odds; otherwise falls back to model fair odds.
        """
        self.real_lines = real_lines or {}

    def _leg_from_prop(self, prop) -> CalcLeg:
        """Build a calc leg from a ranked prop, using real odds if available."""
        side = getattr(prop, "side", "over")
        # Model probability (L10/L15 blend, tempered)
        l10 = (prop.l10_under if side == "under" else prop.l10_rate) / 100.0
        l15 = (prop.l15_under if side == "under" else prop.l15_rate) / 100.0
        prob = round((l10 * 0.6 + l15 * 0.4) * 0.85 + 0.5 * 0.15, 4)

        # Real odds if we have them
        key = (prop.player_name, side)
        real = self.real_lines.get(key)
        if real is not None:
            dec = american_to_decimal(real)
            source = "real"
        else:
            dec = prob_to_fair_decimal(prob)
            source = "model"

        return CalcLeg(
            player_name=prop.player_name,
            prop_label=prop.prop_label,
            side=side,
            decimal_odds=dec,
            hit_prob=prob,
            odds_source=source,
            game_matchup=getattr(prop, "game_matchup", ""),
        )

    def find_parlays(self, props: list, stake: float,
                     target_payout: float = None,
                     target_multiplier: float = None,
                     max_legs: int = 5, top_pool: int = 18,
                     tolerance: float = 0.25) -> list:
        """
        Find parlays whose payout lands near the target.

        stake:            $ you put in
        target_payout:    $ you want back (total), OR
        target_multiplier: e.g. 10 for 10x
        tolerance:        how close to target counts (0.25 = within 25%)

        Returns list of CalcParlay sorted by combined probability (safest
        first) among those that hit the target range.
        """
        if target_multiplier is None and target_payout is not None:
            target_multiplier = target_payout / stake if stake else 1
        if target_multiplier is None:
            target_multiplier = 5  # default

        # Build legs from top props (skip any with no odds)
        legs = []
        for p in props[:top_pool]:
            leg = self._leg_from_prop(p)
            if leg.decimal_odds and leg.decimal_odds > 1:
                legs.append(leg)

        lo = target_multiplier * (1 - tolerance)
        hi = target_multiplier * (1 + tolerance)

        results = []
        for n in range(1, max_legs + 1):
            for combo in combinations(legs, n):
                # no duplicate players
                names = [l.player_name for l in combo]
                if len(set(names)) < len(names):
                    continue
                combined_dec = 1.0
                combined_prob = 1.0
                for leg in combo:
                    combined_dec *= leg.decimal_odds
                    combined_prob *= leg.hit_prob
                if lo <= combined_dec <= hi:
                    payout = round(stake * combined_dec, 2)
                    results.append(CalcParlay(
                        legs=list(combo),
                        num_legs=n,
                        combined_decimal=round(combined_dec, 3),
                        combined_prob=round(combined_prob, 4),
                        stake=stake,
                        payout=payout,
                        profit=round(payout - stake, 2),
                        odds_source=("real" if all(l.odds_source == "real"
                                                   for l in combo) else "mixed/model"),
                    ))

        # Sort by highest combined probability (safest way to hit the target)
        results.sort(key=lambda x: x.combined_prob, reverse=True)
        return results[:15]
