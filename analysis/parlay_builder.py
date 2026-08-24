"""
analysis/parlay_builder.py

Builds optimal parlay combinations from ranked props.

Key principles (what makes this smart, not a trap):
1. HONEST PROBABILITY — combined win % is the product of legs (adjusted
   for correlation). Three 75% legs = ~42%, and we SHOW that number.
2. CORRELATION AWARENESS:
   - NEGATIVE correlation (bad): stacking multiple hitters vs the same
     pitcher — if he's on, they all miss together. We penalize this.
   - POSITIVE correlation (good): same pitcher's Ks + outs from one
     dominant start tend to hit together. We can exploit this.
3. BOTH same-game stacks AND cross-game parlays, clearly labeled.

Uses the model's hit rate (L10/L15 blend) as each leg's probability.
Real sportsbook odds require OddsAPI credits (Sept 1) — until then this
shows model probability; when credits return it layers in actual lines.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from itertools import combinations
from loguru import logger


@dataclass
class ParlayLeg:
    player_name:  str
    prop_label:   str
    team:         str
    game_matchup: str
    hit_prob:     float          # 0-1 model probability
    tier:         str
    is_pitcher:   bool
    prop_stat:    str


@dataclass
class Parlay:
    legs:          list          # list[ParlayLeg]
    num_legs:      int
    combined_prob: float         # honest combined probability (0-1)
    parlay_type:   str           # "same-game" / "cross-game"
    correlation:   str           # "positive" / "negative" / "neutral"
    avg_tier:      str
    warning:       str = ""
    fair_odds:     str = ""      # American odds implied by combined_prob


def _prob_to_american(prob: float) -> str:
    """Convert a probability to fair American odds (no vig)."""
    if prob <= 0 or prob >= 1:
        return "N/A"
    decimal = 1 / prob
    if decimal >= 2:
        return f"+{round((decimal - 1) * 100)}"
    else:
        return f"-{round(100 / (decimal - 1))}"


class ParlayBuilder:
    """Builds and ranks parlay combinations."""

    def __init__(self):
        pass

    def _leg_prob(self, prop) -> float:
        """
        Model probability for a leg = blend of L10 and L15 hit rates.
        Slightly discounted toward the mean to avoid overconfidence
        from small samples (regression to reality).
        """
        l10 = prop.l10_rate / 100.0
        l15 = prop.l15_rate / 100.0
        raw = l10 * 0.6 + l15 * 0.4
        # Regress 15% toward 0.5 to temper extreme rates
        return round(raw * 0.85 + 0.5 * 0.15, 4)

    def _detect_correlation(self, legs: list) -> str:
        """
        Determine correlation type among legs.
        - Multiple batters, same game, vs same pitcher = NEGATIVE (risky)
        - Same pitcher's own props (Ks + outs) = POSITIVE
        - Different games = NEUTRAL (independent)
        """
        games = set(l.game_matchup for l in legs)
        if len(games) > 1:
            return "neutral"  # cross-game = independent

        # Same game
        pitchers = [l for l in legs if l.is_pitcher]
        batters = [l for l in legs if not l.is_pitcher]

        # Same pitcher, multiple of his own props = positive
        if len(pitchers) >= 2:
            pitcher_names = set(l.player_name for l in pitchers)
            if len(pitcher_names) == 1:
                return "positive"

        # Multiple batters same game facing the same pitcher = negative
        if len(batters) >= 2:
            return "negative"

        return "neutral"

    def _combined_prob(self, legs: list, correlation: str) -> float:
        """
        Combined probability with correlation adjustment.
        Independent: product of legs.
        Negative correlation: product is optimistic — discount it.
        Positive correlation: legs tend to hit together — slight boost.
        """
        product = 1.0
        for leg in legs:
            product *= leg.hit_prob

        if correlation == "negative":
            # Legs fail together more than independence assumes — discount
            product *= 0.85
        elif correlation == "positive":
            # Legs hit together more than independence assumes — slight boost
            product *= 1.10
            product = min(product, min(l.hit_prob for l in legs))  # cap at weakest leg

        return round(product, 4)

    def _avg_tier(self, legs: list) -> str:
        tier_val = {"A": 3, "B": 2, "C": 1, "pass": 0}
        val_tier = {3: "A", 2: "B", 1: "C", 0: "pass"}
        avg = sum(tier_val.get(l.tier, 0) for l in legs) / len(legs)
        return val_tier.get(round(avg), "B")

    def build_parlays(self, props: list, max_legs: int = 4,
                     top_pool: int = 15) -> dict:
        """
        Build the best parlays of each size from the top props.
        Returns {2: [Parlay...], 3: [...], 4: [...]}.
        """
        # Convert top props to legs
        pool = []
        for p in props[:top_pool]:
            prob = self._leg_prob(p)
            pool.append(ParlayLeg(
                player_name=p.player_name,
                prop_label=p.prop_label,
                team=p.team,
                game_matchup=p.game_matchup,
                hit_prob=prob,
                tier=p.tier,
                is_pitcher=p.is_pitcher,
                prop_stat=p.prop_stat,
            ))

        # Avoid duplicate player+different-prop in same parlay
        results = {}
        for n in range(2, max_legs + 1):
            parlays = []
            for combo in combinations(pool, n):
                # Skip if same player appears twice
                names = [l.player_name for l in combo]
                if len(set(names)) < len(names):
                    continue

                correlation = self._detect_correlation(list(combo))
                combined = self._combined_prob(list(combo), correlation)
                games = set(l.game_matchup for l in combo)
                ptype = "same-game" if len(games) == 1 else "cross-game"

                warning = ""
                if correlation == "negative":
                    warning = ("⚠️ Same-game hitters vs same pitcher — they can "
                              "all miss together if he's on. Higher risk than the "
                              "number suggests.")
                elif combined < 0.25:
                    warning = "⚠️ Low combined probability — long shot."

                parlay = Parlay(
                    legs=list(combo),
                    num_legs=n,
                    combined_prob=combined,
                    parlay_type=ptype,
                    correlation=correlation,
                    avg_tier=self._avg_tier(list(combo)),
                    warning=warning,
                    fair_odds=_prob_to_american(combined),
                )
                parlays.append(parlay)

            # Sort by combined probability, keep top 10
            parlays.sort(key=lambda x: x.combined_prob, reverse=True)
            results[n] = parlays[:10]

        return results

    def best_overall(self, props: list) -> dict:
        """
        Return the single best parlay of each type/size for a quick view.
        """
        all_parlays = self.build_parlays(props)
        best = {}

        # Best safe (highest prob, any size)
        flat = [p for sublist in all_parlays.values() for p in sublist]
        if flat:
            flat.sort(key=lambda x: x.combined_prob, reverse=True)
            best["safest"] = flat[0]

            # Best cross-game (spread risk)
            cross = [p for p in flat if p.parlay_type == "cross-game"]
            if cross:
                best["cross_game"] = cross[0]

            # Best positive-correlation same-game
            pos = [p for p in flat if p.correlation == "positive"]
            if pos:
                best["correlated"] = pos[0]

        return {"by_size": all_parlays, "highlights": best}
