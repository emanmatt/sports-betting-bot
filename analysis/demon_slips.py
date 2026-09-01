"""
analysis/demon_slips.py

"Demon" slips — high-risk, high-reward long-shot plays surfaced by
SITUATIONAL factors rather than just recent form:

  - Injury opportunity: a regular is hurt, so a backup/next-man-up gets
    more playing time or a better lineup spot than usual
  - Contract year / motivation: player with extra incentive
  - Role change: someone recently moved up in the order or into a
    starting role
  - Favorable extreme: hot streak + great park + weak opposing pitcher
    stacking together for an outlier ceiling

These are LONG SHOTS by design — bigger props (2+ hits, HR, high
strikeouts) where the situation gives an outside shot at a big night.
The module is honest that these are high variance: low hit probability,
high payout. Never presented as safe.

Demon slips are the opposite of the Value tab's edge plays. Value =
steady, small edges. Demons = swing for the fences, accept you'll miss
most of the time. Both have a place; the app labels which is which.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field


@dataclass
class DemonPlay:
    player_name:  str
    prop_label:   str
    team:         str
    game_matchup: str
    hit_prob:     float           # model prob (usually low — it's a long shot)
    factors:      list = field(default_factory=list)   # why it's flagged
    demon_score:  float = 0.0     # situational upside score
    tier:         str = ""


# Rare/ceiling props that make good "demon" targets (big payout when they hit)
DEMON_PROPS = {
    "Home Run", "2+ Hits", "3+ Total Bases", "3+ H+R+RBI",
    "Hitter Fantasy 10+", "2+ RBI", "6+ Strikeouts", "Pitcher Fantasy 15+",
}


class DemonSlipBuilder:
    """Surfaces high-variance situational plays."""

    def build(self, props: list, injuries: dict = None,
              contracts: dict = None) -> list:
        """
        props:     ranked PropRank objects (need .contract_flag, .park_adj,
                   .pitcher_adj, .weather_boost, .batting_order, etc.)
        injuries:  optional {team: [injured player names]} — flags backups
        contracts: optional {player: 'contract year'} — already on prop.contract_flag

        Returns DemonPlay list sorted by situational upside.
        """
        injuries = injuries or {}
        demons = []

        for p in props:
            # Only consider ceiling props for demons
            if p.prop_label not in DEMON_PROPS:
                continue

            factors = []
            score = 0.0

            # Factor 1: contract-year motivation (from existing flag)
            if getattr(p, "contract_flag", ""):
                factors.append("⚡ Contract year")
                score += 3

            # Factor 2: favorable park for a ceiling game
            if getattr(p, "park_adj", 0) >= 5:
                factors.append("🏟️ Hitter park")
                score += 3

            # Factor 3: weak opposing pitcher (soft matchup = ceiling shot)
            if getattr(p, "pitcher_adj", 0) >= 4:
                factors.append("🎯 Soft pitcher matchup")
                score += 4

            # Factor 4: weak opposing team/staff
            if getattr(p, "team_adj", 0) >= 4:
                factors.append("📉 Weak opposing staff")
                score += 3

            # Factor 5: weather boost
            if getattr(p, "weather_boost", False):
                factors.append("💨 Weather boost")
                score += 2

            # Factor 6: top of the order (more chances)
            if getattr(p, "batting_order", None) and p.batting_order <= 3:
                factors.append("🔝 Top of order")
                score += 3

            # Factor 7: favorable platoon
            if getattr(p, "platoon_adj", 0) >= 3:
                factors.append("🟢 Platoon edge")
                score += 2

            # Factor 8: hot recent form even on this ceiling prop
            if p.l10_rate >= 40:  # for a rare prop, 40%+ is notably hot
                factors.append(f"🔥 Hitting it {p.l10_rate:.0f}% recently")
                score += 4

            # Injury opportunity: is a teammate hurt? (opens playing time)
            hurt = injuries.get(p.team, [])
            if hurt:
                factors.append(f"🚑 Teammate out ({len(hurt)}) — more opportunity")
                score += 3

            # Need at least 2 stacking factors to be a "demon" (not random)
            if len(factors) >= 2:
                demons.append(DemonPlay(
                    player_name=p.player_name,
                    prop_label=p.prop_label,
                    team=p.team,
                    game_matchup=getattr(p, "game_matchup", ""),
                    hit_prob=round((p.l10_rate * 0.6 + p.l15_rate * 0.4) / 100.0, 4),
                    factors=factors,
                    demon_score=round(score, 1),
                    tier=p.tier,
                ))

        demons.sort(key=lambda x: x.demon_score, reverse=True)
        return demons
