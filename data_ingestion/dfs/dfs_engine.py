"""
data_ingestion/dfs/dfs_engine.py

Pulls projections from DFS pick'em apps (PrizePicks, Underdog)
and compares them against sportsbook consensus lines.

The edge: DFS apps set their own lines. When a PrizePicks line
differs from the sportsbook market, that's a potential edge —
if the market says a player's line "should" be 26.5 but PrizePicks
has it at 24.5, taking the OVER on PrizePicks has positive expected value.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from datetime import datetime
from dataclasses import dataclass, field
from loguru import logger

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# PrizePicks public projections endpoint
PRIZEPICKS_URL = "https://api.prizepicks.com/projections"

# Stat type mapping between DFS apps and our normalized types
STAT_NORMALIZE = {
    "Points":            "points",
    "Rebounds":          "rebounds",
    "Assists":           "assists",
    "3-PT Made":         "threes",
    "Pass Yards":        "pass_yds",
    "Rush Yards":        "rush_yds",
    "Receiving Yards":   "rec_yds",
    "Receptions":        "receptions",
    "Hits":              "hits",
    "Total Bases":       "total_bases",
    "Home Runs":         "home_runs",
    "Pitcher Strikeouts": "strikeouts",
    "Strikeouts":        "strikeouts",
    "Shots On Goal":     "shots",
    "Goals":             "goals",
}


@dataclass
class DFSProjection:
    """A single DFS app projection line."""
    app:          str          # "prizepicks" / "underdog"
    player_name:  str
    team:         str
    sport:        str
    stat_type:    str          # normalized
    stat_label:   str          # display
    line:         float
    # Comparison to sportsbook (filled in later)
    market_line:  float = None
    edge:         float = None       # market_line - dfs_line
    edge_direction: str = ""         # over / under / none
    edge_pct:     float = None
    captured_at:  datetime = field(default_factory=datetime.utcnow)


class DFSEngine:
    """Pulls DFS projections and finds edges vs sportsbook market."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ── PrizePicks ─────────────────────────────────────────────────────

    def fetch_prizepicks(self, sport: str = None) -> list[DFSProjection]:
        """
        Fetch PrizePicks projections.
        Their API returns projections + included player data.
        """
        # League IDs on PrizePicks
        league_ids = {
            "NBA": 7, "NFL": 9, "MLB": 2, "NHL": 8,
        }

        params = {"per_page": 250, "single_stat": "true"}
        if sport and sport in league_ids:
            params["league_id"] = league_ids[sport]

        try:
            resp = self.session.get(PRIZEPICKS_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"[DFS] PrizePicks fetch failed: {e}")
            return []

        # Build player lookup from included data
        players = {}
        for item in data.get("included", []):
            if item.get("type") == "new_player":
                pid = item.get("id")
                attrs = item.get("attributes", {})
                players[pid] = {
                    "name": attrs.get("name", ""),
                    "team": attrs.get("team", ""),
                    "league": attrs.get("league", ""),
                }

        projections = []
        for item in data.get("data", []):
            if item.get("type") != "projection":
                continue
            attrs = item.get("attributes", {})
            rel = item.get("relationships", {})

            # Get player
            player_ref = rel.get("new_player", {}).get("data", {})
            player_id = player_ref.get("id")
            player_info = players.get(player_id, {})

            stat_label = attrs.get("stat_type", "")
            stat_type = STAT_NORMALIZE.get(stat_label, stat_label.lower())
            line = attrs.get("line_score")

            if not player_info.get("name") or line is None:
                continue

            projections.append(DFSProjection(
                app="prizepicks",
                player_name=player_info["name"],
                team=player_info.get("team", ""),
                sport=sport or player_info.get("league", ""),
                stat_type=stat_type,
                stat_label=stat_label,
                line=float(line),
            ))

        logger.info(f"[DFS] PrizePicks: {len(projections)} projections for {sport}.")
        return projections

    # ── Underdog ───────────────────────────────────────────────────────

    def fetch_underdog(self, sport: str = None) -> list[DFSProjection]:
        """
        Fetch Underdog Fantasy projections.
        Note: Underdog's API structure changes — this is best-effort.
        """
        url = "https://api.underdogfantasy.com/beta/v5/over_under_lines"
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"[DFS] Underdog fetch failed (may need auth): {e}")
            return []

        projections = []
        # Underdog structures: over_under_lines + players + appearances
        players = {p["id"]: p for p in data.get("players", [])}

        for line_item in data.get("over_under_lines", []):
            ou = line_item.get("over_under", {})
            stat = ou.get("appearance_stat", {})
            stat_label = stat.get("display_stat", "")
            stat_type = STAT_NORMALIZE.get(stat_label, stat_label.lower())
            line_val = line_item.get("stat_value")

            player_id = stat.get("player_id")
            player = players.get(player_id, {})
            name = f"{player.get('first_name','')} {player.get('last_name','')}".strip()

            if not name or line_val is None:
                continue

            projections.append(DFSProjection(
                app="underdog",
                player_name=name,
                team=player.get("team_name", ""),
                sport=sport or "",
                stat_type=stat_type,
                stat_label=stat_label,
                line=float(line_val),
            ))

        logger.info(f"[DFS] Underdog: {len(projections)} projections.")
        return projections

    # ── Edge Detection ─────────────────────────────────────────────────

    def compare_to_market(self, dfs_projections: list[DFSProjection],
                          market_props: list) -> list[DFSProjection]:
        """
        Compare DFS lines to sportsbook consensus.
        market_props: list of MultiBookProp from multibook_engine.

        The edge: if sportsbook consensus is higher than the DFS line,
        the OVER on the DFS app has value (and vice versa).
        """
        # Build market lookup: (player_lastname, stat_type) -> consensus_line
        market_lookup = {}
        for mp in market_props:
            last_name = mp.player_name.split()[-1].lower() if mp.player_name else ""
            key = (last_name, mp.prop_type)
            market_lookup[key] = mp.consensus_line or mp.main_line

        for dfs in dfs_projections:
            last_name = dfs.player_name.split()[-1].lower() if dfs.player_name else ""
            key = (last_name, dfs.stat_type)
            market_line = market_lookup.get(key)

            if market_line is None:
                continue

            dfs.market_line = market_line
            dfs.edge = round(market_line - dfs.line, 1)

            # If market > DFS line: OVER on DFS has value
            # If market < DFS line: UNDER on DFS has value
            if dfs.edge > 0.5:
                dfs.edge_direction = "over"
            elif dfs.edge < -0.5:
                dfs.edge_direction = "under"
            else:
                dfs.edge_direction = "none"

            if dfs.line:
                dfs.edge_pct = round(abs(dfs.edge) / dfs.line * 100, 1)

        # Return only projections with a market comparison
        return [d for d in dfs_projections if d.market_line is not None]

    def find_dfs_edges(self, sport: str, market_props: list) -> list[DFSProjection]:
        """
        Full pipeline: fetch DFS lines, compare to market, return edges.
        """
        all_dfs = []

        # PrizePicks
        pp = self.fetch_prizepicks(sport)
        all_dfs.extend(pp)

        # Underdog (best effort)
        try:
            ud = self.fetch_underdog(sport)
            all_dfs.extend(ud)
        except Exception:
            pass

        if not all_dfs:
            logger.info(f"[DFS] No DFS projections found for {sport}.")
            return []

        # Compare to market
        edges = self.compare_to_market(all_dfs, market_props)

        # Sort by edge size
        edges_with_value = [e for e in edges if e.edge_direction != "none"]
        edges_with_value.sort(key=lambda x: abs(x.edge or 0), reverse=True)

        logger.info(f"[DFS] {sport}: {len(edges_with_value)} DFS edges found "
                   f"(of {len(edges)} compared).")
        return edges_with_value
