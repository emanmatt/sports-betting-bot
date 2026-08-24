"""
analysis/prop_ranker.py

Universal prop ranker — ranks EVERY prop type together so you see
the single best play across all of them, not just hits.

Prop types ranked:
  BATTERS:  hits (1+), total bases (2+), RBI (1+), home run (1+), runs (1+)
  PITCHERS: strikeouts (over common lines: 4.5, 5.5, 6.5)

Each prop gets a hit-rate over a standard line + a 0-100 score,
then all props sort together strongest → weakest.
No OddsAPI credits needed — pure game-log math.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from loguru import logger
from database.models import get_session, PlayerStats

# Standard prop lines to evaluate each stat against
# (stat, line, label) — "hit" means value > line
BATTER_PROPS = [
    ("hits",           0.5, "1+ Hits"),
    ("hits",           1.5, "2+ Hits"),
    ("total_bases",    1.5, "2+ Total Bases"),
    ("total_bases",    2.5, "3+ Total Bases"),
    ("rbi",            0.5, "1+ RBI"),
    ("runs",           0.5, "1+ Runs"),
    ("home_runs",      0.5, "Home Run"),
    ("hits_runs_rbis", 1.5, "2+ H+R+RBI"),
    ("hits_runs_rbis", 2.5, "3+ H+R+RBI"),
    ("hitter_fantasy", 7.5, "Hitter Fantasy 8+"),
    ("hitter_fantasy", 9.5, "Hitter Fantasy 10+"),
    ("stolen_bases",   0.5, "Stolen Base"),
]

PITCHER_PROPS = [
    ("strikeouts",      4.5, "5+ Strikeouts"),
    ("strikeouts",      5.5, "6+ Strikeouts"),
    ("strikeouts",      6.5, "7+ Strikeouts"),
    ("outs",           15.5, "16+ Outs (5.1 IP)"),
    ("outs",           17.5, "18+ Outs (6 IP)"),
    ("hits_allowed",    5.5, "Over 5.5 Hits Allowed"),
    ("hits_allowed",    6.5, "Over 6.5 Hits Allowed"),
    ("pitcher_fantasy", 14.5, "Pitcher Fantasy 15+"),
    ("pitcher_fantasy", 17.5, "Pitcher Fantasy 18+"),
]


@dataclass
class PropRank:
    player_name:   str
    team:          str
    opponent:      str
    venue:         str
    is_pitcher:    bool
    prop_stat:     str          # hits / total_bases / strikeouts etc
    prop_label:    str          # "2+ Total Bases"
    prop_line:     float
    # Hit rates over this line
    l10_rate:      float = 0.0
    l15_rate:      float = 0.0
    season_rate:   float = 0.0
    games:         int = 0
    avg_value:     float = 0.0
    recent_avg:    float = 0.0
    trend:         str = ""
    # Context
    batting_order: int = None
    weather_boost: bool = False
    weather_note:  str = ""
    # New context factors
    park_note:      str = ""
    park_adj:       float = 0.0
    pitcher_note:   str = ""
    pitcher_adj:    float = 0.0
    injury_flag:    str = ""       # "" / "Questionable" / "Out"
    fatigue_note:   str = ""
    fatigue_adj:    float = 0.0
    contract_flag:  str = ""       # "⚡ Contract year" when known
    opp_pitcher:   str = ""
    game_status:   str = "upcoming"   # upcoming / live
    game_label:    str = ""
    # Score
    score:         float = 0.0
    tier:          str = ""
    game_log:      list = field(default_factory=list)


class PropRanker:
    """Ranks all prop types together."""

    def __init__(self):
        self.db = get_session()
        self._logs_by_name = None

    def close(self):
        self.db.close()

    def _load_logs(self):
        """Load all logs once, grouped by player name."""
        if self._logs_by_name is not None:
            return
        self._logs_by_name = {}
        all_stats = self.db.query(PlayerStats).filter(
            PlayerStats.sport == "MLB"
        ).all()
        for s in all_stats:
            if not s.raw_stats:
                continue
            nm = s.raw_stats.get("player_name")
            if not nm:
                continue
            self._logs_by_name.setdefault(nm, []).append(s)

    def _get_stat_values(self, player_name: str, stat: str) -> list[float]:
        """Get game-by-game values for a stat from raw_stats."""
        self._load_logs()
        rows = self._logs_by_name.get(player_name)
        if not rows:
            # case-insensitive fallback
            for nm, r in self._logs_by_name.items():
                if nm.lower() == player_name.lower():
                    rows = r
                    break
        if not rows:
            return []

        # Sort by actual game DATE descending (most recent first).
        # game_id string sort is NOT chronological — that was the bug
        # that made stale high-hit games look like the recent 10.
        def _date_key(s):
            rs = s.raw_stats or {}
            return rs.get("date", "")
        rows = sorted(rows, key=_date_key, reverse=True)[:20]
        values = []
        for s in rows:
            rs = s.raw_stats or {}
            v = rs.get(stat)
            if v is not None:
                try:
                    values.append(float(v))
                except (ValueError, TypeError):
                    pass
        return values

    def _rate_over(self, values: list[float], line: float) -> float:
        """% of games where value > line."""
        if not values:
            return 0.0
        return round(sum(1 for v in values if v > line) / len(values) * 100)

    def _score(self, pr: PropRank) -> float:
        """
        0-100 composite score.
        Weights: recent form ~40%, opposing pitcher 20%, park 10%,
        plus batting order, weather, and rest/fatigue as adjustments.
        Injury applies as a penalty/drop.
        """
        score = 0.0
        # Recent form core (~40 pts from L10, 15 from L15)
        score += pr.l10_rate * 0.40
        score += pr.l15_rate * 0.15

        # Recent form momentum
        if pr.recent_avg > pr.avg_value * 1.15:
            score += 8
        elif pr.recent_avg >= pr.avg_value:
            score += 4

        # Opposing pitcher quality (batters only) — up to +8 / -12
        if not pr.is_pitcher:
            score += pr.pitcher_adj

        # Park factor (batters only) — hitter parks help, pitcher parks hurt
        if not pr.is_pitcher:
            score += pr.park_adj * 0.6   # scale it down a touch

        # Weather (batters)
        if pr.weather_boost and not pr.is_pitcher:
            score += 6

        # Batting order (batters)
        if pr.batting_order and not pr.is_pitcher:
            if pr.batting_order <= 3:
                score += 8
            elif pr.batting_order <= 5:
                score += 4

        # Rest / fatigue adjustment (can be negative)
        score += pr.fatigue_adj

        # Trend penalty
        if pr.trend == "cold":
            score -= 8

        # Thin sample penalty
        if pr.games < 8:
            score -= 15

        # Injury penalty
        if pr.injury_flag == "Questionable":
            score -= 12
        elif pr.injury_flag == "Out":
            score -= 100   # effectively drops it

        return max(0, min(100, round(score, 1)))

    def _tier(self, score: float) -> str:
        if score >= 70: return "A"
        if score >= 55: return "B"
        if score >= 40: return "C"
        return "pass"

    def _build_prop(self, player_name, team, opponent, venue,
                    is_pitcher, stat, line, label,
                    batting_order=None, weather_boost=False,
                    weather_note="", opp_pitcher="",
                    game_status="upcoming",
                    park_adj=0.0, park_note="",
                    pitcher_adj=0.0, pitcher_note="",
                    injury_flag="", fatigue_adj=0.0, fatigue_note="",
                    contract_flag="") -> PropRank:
        values = self._get_stat_values(player_name, stat)
        if not values:
            return None

        # HR props use HR park factor, not hits
        is_hr = stat == "home_runs"

        pr = PropRank(
            player_name=player_name, team=team, opponent=opponent,
            venue=venue, is_pitcher=is_pitcher, prop_stat=stat,
            prop_label=label, prop_line=line,
            batting_order=batting_order, weather_boost=weather_boost,
            weather_note=weather_note, opp_pitcher=opp_pitcher,
            game_status=game_status,
            game_label=("🔴 LIVE" if game_status == "live" else "Upcoming"),
            park_adj=park_adj, park_note=park_note,
            pitcher_adj=pitcher_adj, pitcher_note=pitcher_note,
            injury_flag=injury_flag,
            fatigue_adj=fatigue_adj, fatigue_note=fatigue_note,
            contract_flag=contract_flag,
        )
        pr.games = len(values)
        pr.l10_rate = self._rate_over(values[:10], line)
        pr.l15_rate = self._rate_over(values[:15], line)
        pr.season_rate = self._rate_over(values, line)
        pr.avg_value = round(sum(values) / len(values), 2)
        l5 = values[:5]
        pr.recent_avg = round(sum(l5) / len(l5), 2) if l5 else 0
        pr.game_log = [int(v) if v == int(v) else v for v in values[:10]]

        if pr.recent_avg > pr.avg_value * 1.15:
            pr.trend = "hot"
        elif pr.recent_avg < pr.avg_value * 0.85:
            pr.trend = "cold"
        else:
            pr.trend = "stable"

        pr.score = self._score(pr)
        pr.tier = self._tier(pr.score)
        return pr

    def rank_all_props(self, lineups_data: list,
                       weather_by_venue: dict = None) -> list[PropRank]:
        """
        Rank EVERY prop type across all confirmed lineups + pitchers.
        """
        weather_by_venue = weather_by_venue or {}
        props = []

        # Lazy-load factor helpers
        from analysis.park_factors import park_score_adjustment, park_note
        try:
            from analysis.pitcher_matchup import PitcherMatchup
            matchup = PitcherMatchup()
        except Exception:
            matchup = None

        for game in lineups_data:
            venue = game.get("venue", "")
            game_status = game.get("status", "upcoming")
            weather = weather_by_venue.get(venue)
            wboost = False
            wnote = ""
            if weather:
                wnote = getattr(weather, "impact_summary", "")
                wboost = getattr(weather, "wind_effect", "") == "out" or \
                        (getattr(weather, "temp_f", 0) or 0) >= 85

            # Park factor for this venue (computed once)
            pk_adj = park_score_adjustment(venue)
            pk_note = park_note(venue)

            # ── BATTERS ──
            for side, team_k, opp_k, pitch_k, pitch_id_k in [
                ("home_lineup", "home_team", "away_team", "away_pitcher", "away_pitcher_id"),
                ("away_lineup", "away_team", "home_team", "home_pitcher", "home_pitcher_id"),
            ]:
                lineup = game.get(side, [])
                team = game.get(team_k, "")
                opp = game.get(opp_k, "")
                opp_pitcher = game.get(pitch_k, "")
                opp_pitcher_id = game.get(pitch_id_k)

                # Opposing pitcher quality (computed once per lineup side)
                pq_adj, pq_note = 0.0, ""
                if matchup and opp_pitcher:
                    try:
                        pq = matchup.get_pitcher_quality(opp_pitcher, opp_pitcher_id)
                        pq_adj, pq_note = pq.adjustment, pq.note
                    except Exception:
                        pass

                for batter in lineup:
                    name = batter.get("name") if isinstance(batter, dict) else batter
                    order_raw = batter.get("batting_order") if isinstance(batter, dict) else None
                    order = None
                    if order_raw is not None:
                        try:
                            o = int(order_raw)
                            order = o // 100 if o >= 100 else o
                        except (ValueError, TypeError):
                            order = None

                    # Injury flag from batter dict if present
                    inj_flag = ""
                    if isinstance(batter, dict):
                        inj_flag = batter.get("injury_flag", "")

                    for stat, line, label in BATTER_PROPS:
                        pr = self._build_prop(
                            name, team, opp, venue, False, stat, line, label,
                            batting_order=order, weather_boost=wboost,
                            weather_note=wnote, opp_pitcher=opp_pitcher,
                            game_status=game_status,
                            park_adj=pk_adj, park_note=pk_note,
                            pitcher_adj=pq_adj, pitcher_note=pq_note,
                            injury_flag=inj_flag,
                        )
                        if pr and pr.games >= 5:  # need enough sample
                            props.append(pr)

            # ── PITCHERS ──
            for pitcher_name, team, opp in [
                (game.get("home_pitcher"), game.get("home_team"), game.get("away_team")),
                (game.get("away_pitcher"), game.get("away_team"), game.get("home_team")),
            ]:
                if not pitcher_name:
                    continue
                for stat, line, label in PITCHER_PROPS:
                    pr = self._build_prop(
                        pitcher_name, team, opp, venue, True, stat, line, label,
                        opp_pitcher="", game_status=game_status,
                        park_note=pk_note,
                    )
                    if pr and pr.games >= 5:
                        props.append(pr)

        # Sort strongest to weakest across ALL prop types
        props.sort(key=lambda x: x.score, reverse=True)
        logger.info(f"[PropRanker] Ranked {len(props)} props across all types.")
        return props

    def to_table_rows(self, props: list[PropRank], limit: int = 60) -> list[dict]:
        rows = []
        for i, p in enumerate(props[:limit], 1):
            trend_emoji = {"hot": "🔥", "cold": "🧊", "stable": "➡️"}.get(p.trend, "")
            rows.append({
                "Rank": i,
                "Tier": p.tier,
                "Status": p.game_label,
                "Player": p.player_name,
                "Prop": p.prop_label,
                "Type": "Pitcher" if p.is_pitcher else "Batter",
                "Team": p.team,
                "L10": f"{p.l10_rate:.0f}%",
                "L15": f"{p.l15_rate:.0f}%",
                "Season": f"{p.season_rate:.0f}%",
                "Avg": p.avg_value,
                "Trend": f"{trend_emoji}",
                "vs": p.opp_pitcher or p.opponent or "-",
                "Matchup": ("🔴 Tough" if p.pitcher_adj <= -5 else
                           "🟢 Soft" if p.pitcher_adj >= 4 else "➖") if not p.is_pitcher else "-",
                "Park": ("🟢" if p.park_adj >= 5 else
                        "🔴" if p.park_adj <= -5 else "➖"),
                "Flags": " ".join(filter(None, [
                    "⚠️" + p.injury_flag if p.injury_flag else "",
                    p.contract_flag,
                ])) or "-",
                "Score": p.score,
            })
        return rows
