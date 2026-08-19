"""
tests/test_data.py
Quick check to see how much data is in the database.
Run after the scheduler has been going for a bit.

Usage: python tests/test_data.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import (
    get_session, Team, Player, Game, GameOdds,
    InjuryReport, NewsArticle, SocialPost, PlayerContract, BetSignal
)
from loguru import logger


def check_database():
    db = get_session()
    print("\n" + "=" * 55)
    print("  📊 SPORTS BETTING BOT — DATABASE STATUS")
    print("=" * 55)

    checks = [
        ("🏟️  Teams",           db.query(Team).count()),
        ("👤  Players",          db.query(Player).count()),
        ("📅  Games",            db.query(Game).count()),
        ("📈  Odds Records",     db.query(GameOdds).count()),
        ("🏥  Injury Reports",   db.query(InjuryReport).count()),
        ("📰  News Articles",    db.query(NewsArticle).count()),
        ("💬  Reddit Posts",     db.query(SocialPost).count()),
        ("💰  Player Contracts", db.query(PlayerContract).count()),
        ("🎯  Bet Signals",      db.query(BetSignal).count()),
    ]

    for label, count in checks:
        status = "✅" if count > 0 else "⬜"
        print(f"  {status}  {label:<22} {count:>6,} records")

    print("\n" + "-" * 55)

    # Sport breakdown
    print("  Sport breakdown:")
    for sport in ["NBA", "NFL", "MLB", "NHL"]:
        teams   = db.query(Team).filter_by(sport=sport).count()
        players = db.query(Player).filter_by(sport=sport).count()
        games   = db.query(Game).filter_by(sport=sport).count()
        news    = db.query(NewsArticle).filter_by(sport=sport).count()
        print(f"  {sport}: {teams} teams | {players} players | "
              f"{games} games | {news} news articles")

    print("=" * 55)

    # Most recent odds
    latest_odds = (db.query(GameOdds)
                   .order_by(GameOdds.captured_at.desc())
                   .first())
    if latest_odds:
        print(f"\n  ⏰  Latest odds captured: {latest_odds.captured_at}")
        print(f"      Game: {latest_odds.game_id} | Book: {latest_odds.sportsbook}")
        if latest_odds.spread:
            print(f"      Spread: {latest_odds.spread:+.1f} | "
                  f"Total: {latest_odds.total_over_under}")

    # High-impact news
    high_impact = (db.query(NewsArticle)
                   .filter_by(betting_impact="high")
                   .order_by(NewsArticle.published_at.desc())
                   .limit(3)
                   .all())
    if high_impact:
        print(f"\n  🚨  Recent HIGH-IMPACT news:")
        for article in high_impact:
            print(f"      [{article.sport}] {article.title[:70]}...")

    # Players with incentive clauses
    with_incentives = (db.query(PlayerContract)
                       .filter(PlayerContract.incentives != None)
                       .count())
    if with_incentives > 0:
        print(f"\n  ⚡  Players with incentive clauses: {with_incentives}")

    db.close()
    print("\n  Run 'python scheduler/scheduler.py' if counts are low.\n")


if __name__ == "__main__":
    check_database()
