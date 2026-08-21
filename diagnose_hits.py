"""Diagnostic v2: find which player_id format has the game logs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from database.models import get_session, Player, PlayerStats

db = get_session()

# Get a game log row and see its player_id format
sample_log = db.query(PlayerStats).filter_by(sport="MLB").first()
if sample_log:
    print(f"Sample game log player_id: '{sample_log.player_id}'")
    print(f"  hits column: {sample_log.hits}")
    if sample_log.raw_stats:
        print(f"  raw_stats name: {sample_log.raw_stats.get('player_name','(none)')}")
        print(f"  raw_stats hits: {sample_log.raw_stats.get('hits','(none)')}")
print()

# Count distinct player_id formats in logs
from sqlalchemy import func
log_ids = db.query(PlayerStats.player_id).filter_by(sport="MLB").distinct().limit(5).all()
print("Sample game-log player_ids:")
for (pid,) in log_ids:
    name_match = db.query(Player).filter_by(player_id=pid).first()
    print(f"  '{pid}' -> player row: {name_match.full_name if name_match else 'NO PLAYER ROW'}")
print()

# Now test: for a player WITH logs, can we find them by name?
print("Reverse lookup - find players that HAVE logs:")
players_with_logs = (db.query(Player)
    .join(PlayerStats, Player.player_id == PlayerStats.player_id)
    .filter(Player.sport == "MLB")
    .distinct().limit(5).all())
for p in players_with_logs:
    cnt = db.query(PlayerStats).filter_by(player_id=p.player_id).count()
    print(f"  {p.full_name} (id={p.player_id}): {cnt} logs")

db.close()
