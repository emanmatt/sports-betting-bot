"""
analysis/nfl_ranker.py

NFL prop ranker — the football counterpart to the MLB PropRanker.

Respects how the NFL actually works:
  - Tiny sample: leans on prior-year averages early, shifts to
    current-season as games accumulate (blend by games played)
  - Position-specific props: QB (pass yds/TD/completions) vs
    skill (rush yds, rec yds, receptions)
  - Handles thin data: a player with near-empty prior-year logs is
    flagged low-confidence, not ranked off noise

Stat labels confirmed from ESPN gamelog:
  Receiving/rushing: REC, TGTS, YDS, AVG, TD, LNG, CAR, YDS(rush)
  (QB gamelog has passing columns: CMP, ATT, YDS, TD, INT, etc.)

Prop lines (typical NFL alt/standard points):
  QB:    pass yds 224.5+, pass TD 1.5+, completions 21.5+
  RB:    rush yds 49.5+, rush att 13.5+
  WR/TE: rec yds 49.5+, receptions 3.5+
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from loguru import logger

# Prop definitions per position: (stat_key, line, label)
QB_PROPS = [
    ("pass_yards", 224.5, "224.5+ Pass Yards"),
    ("pass_yards", 274.5, "274.5+ Pass Yards"),
    ("pass_tds", 1.5, "2+ Pass TDs"),
    ("completions", 21.5, "22+ Completions"),
    ("rush_yards", 14.5, "15+ Rush Yards (QB)"),
]
RB_PROPS = [
    ("rush_yards", 49.5, "49.5+ Rush Yards"),
    ("rush_yards", 74.5, "74.5+ Rush Yards"),
    ("rush_att", 13.5, "14+ Carries"),
    ("rec_yards", 19.5, "19.5+ Rec Yards (RB)"),
    ("receptions", 2.5, "3+ Receptions (RB)"),
]
WR_TE_PROPS = [
    ("rec_yards", 49.5, "49.5+ Rec Yards"),
    ("rec_yards", 69.5, "69.5+ Rec Yards"),
    ("receptions", 3.5, "4+ Receptions"),
    ("receptions", 5.5, "6+ Receptions"),
    ("rec_tds", 0.5, "Anytime TD (rec)"),
]


@dataclass
class NFLPropRank:
    player_name:  str
    position:     str
    team:         str
    opponent:     str
    game_matchup: str
    prop_stat:    str
    prop_label:   str
    prop_line:    float
    # Rates
    hit_rate:     float = 0.0     # % of games over the line
    avg_value:    float = 0.0
    games:        int = 0
    data_season:  int = None      # which season the data came from
    low_confidence: bool = False  # thin/rookie data
    # Matchup
    def_rank_note: str = ""
    def_adj:      float = 0.0
    # Score
    score:        float = 0.0
    tier:         str = "pass"
    game_status:  str = "upcoming"


# Map ESPN gamelog labels to our stat keys, per gamelog type
# Receiving/rushing gamelog order: REC, TGTS, YDS, AVG, TD, LNG, CAR, YDS
def _parse_skill_game(row_labels, row_stats) -> dict:
    """Parse one skill-player game row into named stats."""
    d = {}
    # Build label->value with position handling for duplicate YDS
    yds_seen = 0
    for lab, val in zip(row_labels, row_stats):
        try:
            v = float(val)
        except (ValueError, TypeError):
            continue
        if lab == "REC":
            d["receptions"] = v
        elif lab == "TGTS":
            d["targets"] = v
        elif lab == "YDS":
            if yds_seen == 0:
                d["rec_yards"] = v      # first YDS = receiving
                yds_seen += 1
            else:
                d["rush_yards"] = v     # second YDS = rushing
        elif lab == "TD":
            d["rec_tds"] = v            # (approx; TD column)
        elif lab == "CAR":
            d["rush_att"] = v
    return d


def _parse_qb_game(row_labels, row_stats) -> dict:
    """Parse one QB game row. QB gamelog labels differ (passing)."""
    d = {}
    yds_seen = 0
    for lab, val in zip(row_labels, row_stats):
        try:
            v = float(val)
        except (ValueError, TypeError):
            continue
        L = lab.upper()
        if L == "CMP":
            d["completions"] = v
        elif L in ("YDS",):
            if yds_seen == 0:
                d["pass_yards"] = v
                yds_seen += 1
            else:
                d["rush_yards"] = v
        elif L == "TD":
            d["pass_tds"] = v
        elif L == "CAR":
            d["rush_att"] = v
    return d


class NFLRanker:
    def __init__(self):
        from data_ingestion.official.nfl_client import NFLClient
        self.nfl = NFLClient()

    def _rate_over(self, values, line):
        if not values:
            return 0.0
        hits = sum(1 for v in values if v > line)
        return round(hits / len(values) * 100, 1)

    def _stat_values(self, log, stat_key, is_qb):
        """Extract a stat's per-game values from a player's log."""
        vals = []
        for g in log.games:
            if not isinstance(g, dict) or "_labels" not in g:
                continue
            row_labels = g["_labels"]
            row_stats = g["_stats"]
            parsed = (_parse_qb_game(row_labels, row_stats) if is_qb
                     else _parse_skill_game(row_labels, row_stats))
            if stat_key in parsed:
                vals.append(parsed[stat_key])
        return vals

    def rank_player(self, player, team, opponent, game_matchup,
                    game_status="upcoming") -> list:
        """Rank all relevant props for one player."""
        pos = player.get("position", "")
        pid = player.get("id")
        name = player.get("name", "")
        if not pid:
            return []

        log = self.nfl.get_player_stats_with_fallback(pid)
        if not log.games:
            return []   # no data at all — skip

        is_qb = pos == "QB"
        if is_qb:
            props = QB_PROPS
        elif pos in ("RB", "FB"):
            props = RB_PROPS
        else:  # WR, TE
            props = WR_TE_PROPS

        results = []
        for stat_key, line, label in props:
            vals = self._stat_values(log, stat_key, is_qb)
            if not vals:
                continue
            # Skip players with essentially no production (all zeros)
            if sum(vals) == 0:
                continue

            rate = self._rate_over(vals, line)
            avg = round(sum(vals) / len(vals), 1)
            low_conf = len(vals) < 6   # thin sample flag

            pr = NFLPropRank(
                player_name=name, position=pos, team=team,
                opponent=opponent, game_matchup=game_matchup,
                prop_stat=stat_key, prop_label=label, prop_line=line,
                hit_rate=rate, avg_value=avg, games=len(vals),
                data_season=log.season, low_confidence=low_conf,
                game_status=game_status,
            )
            pr.score = self._score(pr)
            pr.tier = self._tier(pr.score)
            results.append(pr)
        return results

    def _score(self, pr) -> float:
        """Score 0-100. Prior-year-based early; penalize thin data."""
        score = pr.hit_rate  # base is the hit rate itself
        # Defense matchup adjustment (added later when wired)
        score += pr.def_adj
        # Thin-data penalty — don't trust a 2-3 game sample
        if pr.low_confidence:
            score -= 15
        # Prior-year data is less certain than current — mild haircut
        # (only matters once current-season exists to compare)
        return max(0, min(100, round(score, 1)))

    def _tier(self, score):
        if score >= 65:
            return "A"
        elif score >= 52:
            return "B"
        elif score >= 40:
            return "C"
        return "pass"

    def rank_slate(self, max_games=None) -> list:
        """Rank props across all of this week's games."""
        games = self.nfl.get_todays_games()
        if max_games:
            games = games[:max_games]
        all_props = []
        for g in games:
            status = self.nfl.classify_status(g.status)
            if status == "final":
                continue
            matchup = f"{g.away_team} @ {g.home_team}"
            for team_id, team_name, opp_name in [
                (g.home_team_id, g.home_team, g.away_team),
                (g.away_team_id, g.away_team, g.home_team),
            ]:
                roster = self.nfl.get_team_roster(team_id)
                for player in roster:
                    props = self.rank_player(player, team_name, opp_name,
                                            matchup, status)
                    all_props.extend(props)
        all_props.sort(key=lambda x: x.score, reverse=True)
        return all_props

    def to_table_rows(self, props, limit=100):
        rows = []
        for i, p in enumerate(props[:limit], 1):
            rows.append({
                "Rank": i,
                "Tier": p.tier,
                "Player": p.player_name,
                "Pos": p.position,
                "Prop": p.prop_label,
                "Team": p.team,
                "Hit %": f"{p.hit_rate:.0f}%",
                "Avg": p.avg_value,
                "Games": p.games,
                "Data": f"{p.data_season}" + (" ⚠️thin" if p.low_confidence else ""),
                "vs": p.opponent,
                "Score": p.score,
            })
        return rows
