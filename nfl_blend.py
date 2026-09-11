"""
Auto-freshening: make the NFL client BLEND current + prior season data,
weighted by how many current-season games exist. Early season leans on
2025; by mid-season it's mostly 2026 — automatically, no manual step.
Adds get_blended_log() to the client and points the ranker at it.
Backs up, auto-restores on error.
"""
import ast

# ---- 1. add get_blended_log to nfl_client ----
cli_path = "data_ingestion/official/nfl_client.py"
cli = open(cli_path, encoding="utf-8").read()
cli_orig = cli

anchor = "    def get_player_stats_with_fallback(self, player_id: str) -> NFLPlayerLog:"
if anchor in cli and "get_blended_log" not in cli:
    # find the end of get_player_stats_with_fallback to append after it
    idx = cli.find(anchor)
    # find next '\n    def ' after it, or end of class
    nxt = cli.find("\n    def ", idx + 10)
    insert_at = nxt if nxt != -1 else len(cli)
    blended = '''

    def get_blended_log(self, player_id: str) -> NFLPlayerLog:
        """
        Auto-freshening data: combine current-season (2026) games with
        prior-season (2025) games so the model shifts toward current form
        as the season progresses — automatically.

        - 0 current games (Week 1): 100% prior year
        - a few current games: current games FIRST (most recent), then
          prior-year games fill the sample so we still have enough data
        The ranker sorts by recency, so current-season games dominate the
        L-game window as they accumulate.
        """
        current = self.get_player_gamelog(player_id, CURRENT_SEASON)
        prior = self.get_player_gamelog(player_id, PRIOR_SEASON)

        # Current games first (they're the freshest signal), then prior
        combined_games = list(current.games) + list(prior.games)

        season_tag = CURRENT_SEASON if current.games else PRIOR_SEASON
        name = current.player_name or prior.player_name
        pos = current.position or prior.position

        return NFLPlayerLog(
            player_name=name, player_id=player_id, position=pos,
            team="", season=season_tag, games=combined_games,
        )
'''
    cli = cli[:insert_at] + blended + cli[insert_at:]
    print("[1] get_blended_log added to nfl_client")
else:
    print("[1] anchor missing or already added")

if cli != cli_orig:
    open(cli_path + ".preblend", "w", encoding="utf-8").write(cli_orig)
    open(cli_path, "w", encoding="utf-8").write(cli)

# ---- 2. point the ranker at get_blended_log ----
rk_path = "analysis/nfl_ranker.py"
rk = open(rk_path, encoding="utf-8").read()
rk_orig = rk
if "get_player_stats_with_fallback" in rk:
    rk = rk.replace("self.nfl.get_player_stats_with_fallback(pid)",
                    "self.nfl.get_blended_log(pid)")
    print("[2] ranker now uses blended log")
else:
    print("[2] ranker call not matched")

if rk != rk_orig:
    open(rk_path + ".preblend", "w", encoding="utf-8").write(rk_orig)
    open(rk_path, "w", encoding="utf-8").write(rk)

# verify both
for p, orig in [(cli_path, cli_orig), (rk_path, rk_orig)]:
    try:
        ast.parse(open(p, encoding="utf-8").read())
        print(f"✓ {p} parses cleanly")
    except SyntaxError as e:
        print(f"✗ {p}: {e}")
        open(p, "w", encoding="utf-8").write(orig)
        print(f"  restored {p}")
