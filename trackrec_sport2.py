"""
Make track_record sport-aware — ONE clean patch, exact-match.
1. log_predictions(sport="MLB") stamps each row's sport
2. get_stats(sport=None) filters by sport (one query change)
Backs up, auto-restores on error.
"""
import ast

path = "analysis/track_record.py"
src = open(path, encoding="utf-8").read()
orig = src

# --- 1. log_predictions signature ---
if 'def log_predictions(self, props: list, top_n: int = 20) -> int:' in src:
    src = src.replace(
        'def log_predictions(self, props: list, top_n: int = 20) -> int:',
        'def log_predictions(self, props: list, top_n: int = 20, sport: str = "MLB") -> int:')
    print("[1] log sig +sport")
else:
    print("[1] log sig not matched")

# --- 2. INSERT columns + values ---
old_ins = """                    (pred_date, player_name, prop_stat, prop_label, prop_line,
                     is_pitcher, team, opponent, game_matchup, tier, score,
                     l10_rate, predicted_side)
                    VALUES
                    (:d, :pn, :ps, :pl, :line, :isp, :team, :opp, :gm, :tier,
                     :score, :l10, :side)"""
new_ins = """                    (pred_date, player_name, prop_stat, prop_label, prop_line,
                     is_pitcher, team, opponent, game_matchup, tier, score,
                     l10_rate, predicted_side, sport)
                    VALUES
                    (:d, :pn, :ps, :pl, :line, :isp, :team, :opp, :gm, :tier,
                     :score, :l10, :side, :sport)"""
if old_ins in src:
    src = src.replace(old_ins, new_ins)
    print("[2] INSERT +sport")
else:
    print("[2] INSERT not matched")

# --- 3. params dict: add "sport": sport. Anchor on '"side": "over",' ---
if '"side": "over",' in src:
    src = src.replace('"side": "over",', '"side": "over", "sport": sport,')
    print("[3] params +sport")
else:
    print("[3] params anchor '\"side\": \"over\",' not found — check")

# --- 4. get_stats: add sport param + filter the one query ---
if 'def get_stats(self) -> dict:' in src:
    src = src.replace('def get_stats(self) -> dict:',
                      'def get_stats(self, sport: str = None) -> dict:')
    old_q = '''            graded = conn.execute(text("""
                SELECT tier, prop_label, is_pitcher, result, score, l10_rate
                FROM predictions WHERE graded = TRUE
            """)).fetchall()'''
    new_q = '''            _sf = f" AND sport = '{sport}'" if sport else ""
            graded = conn.execute(text(
                "SELECT tier, prop_label, is_pitcher, result, score, l10_rate "
                "FROM predictions WHERE graded = TRUE" + _sf
            )).fetchall()'''
    if old_q in src:
        src = src.replace(old_q, new_q)
        print("[4] get_stats +sport filter")
    else:
        print("[4] get_stats query not matched")
else:
    print("[4] get_stats sig not matched")

if src != orig:
    open(path + ".presporttr", "w", encoding="utf-8").write(orig)
    open(path, "w", encoding="utf-8").write(src)

try:
    ast.parse(open(path, encoding="utf-8").read())
    print("✓ track_record.py parses cleanly")
except SyntaxError as e:
    print(f"✗ SYNTAX ERROR: {e}")
    open(path, "w", encoding="utf-8").write(orig)
    print("  restored")
