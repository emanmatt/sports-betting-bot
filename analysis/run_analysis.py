"""
analysis/run_analysis.py

Run AI analysis from the command line.
Works even with limited data — honest about what it can and can't analyze.

Usage:
  # Analyze all news (works with current data):
  python analysis/run_analysis.py --news

  # Analyze a specific sport's games:
  python analysis/run_analysis.py --sport NBA

  # Analyze a specific game:
  python analysis/run_analysis.py --game "Lakers" "Celtics" --sport NBA

  # Full run — all sports, all games:
  python analysis/run_analysis.py --all
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from datetime import datetime
from loguru import logger
from analysis.news_analyzer import NewsAnalyzer
from analysis.ai_engine import AIEngine
from config.settings import SUPPORTED_SPORTS


def print_signal(signal):
    """Pretty-print a bet signal to the console."""
    print("\n" + "=" * 60)
    print(f"  GAME: {signal.game_id}")
    print(f"  Generated: {signal.generated_at.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print(f"  Data Confidence:  {signal.data_confidence}/10")
    print(f"  Team Assessment:  {signal.team_total_score}/10")
    print()

    if signal.is_no_bet:
        print("  🚫 RECOMMENDATION: NO BET")
        print(f"  Reason: {signal.reasoning[:200] if signal.reasoning else 'Insufficient edge identified'}")
    else:
        print(f"  ✅ BET: {signal.bet_selection}")
        print(f"  Type: {signal.bet_type.upper()}")
        print(f"  Confidence: {signal.confidence}/10")
        print(f"  Units: {signal.recommended_units}")
        print(f"  Reasoning: {signal.reasoning[:300]}")

    if signal.red_flags:
        print("\n  🚨 RED FLAGS:")
        for flag in signal.red_flags:
            print(f"    • {flag}")

    if signal.player_props:
        print("\n  ⚡ PLAYER PROPS:")
        for prop in signal.player_props:
            print(f"    • {prop}")

    if signal.line_movement_note:
        print(f"\n  📈 LINE MOVEMENT: {signal.line_movement_note[:200]}")

    if signal.final_note:
        print(f"\n  📌 NOTE: {signal.final_note[:200]}")

    print("=" * 60)


def run_news_analysis():
    """Run news-based analysis — works with current data."""
    print("\n" + "=" * 60)
    print("  📰 NEWS & SIGNAL ANALYSIS")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    analyzer = NewsAnalyzer()
    results = analyzer.run_daily_news_scan()

    for sport, analysis in results.items():
        print(f"\n{'=' * 60}")
        print(f"  {sport} NEWS ANALYSIS")
        print("=" * 60)
        print(analysis)

    if not results:
        print("\n  No news data found in database yet.")
        print("  Run the scheduler first: python scheduler/scheduler.py")


def run_game_analysis(sport: str):
    """Run full game analysis for a sport."""
    print(f"\n  Analyzing {sport} games...")
    engine = AIEngine()
    signals = engine.analyze_todays_games(sport)

    if not signals:
        print(f"  No {sport} games found to analyze.")
        print("  This may mean games haven't loaded yet from ESPN.")
        return

    bets = [s for s in signals if not s.is_no_bet]
    print(f"\n  Analyzed {len(signals)} games → {len(bets)} bets recommended")

    for signal in signals:
        print_signal(signal)


def run_specific_game(home: str, away: str, sport: str):
    """Analyze one specific matchup."""
    print(f"\n  Analyzing: {away} @ {home} ({sport})")
    engine = AIEngine()
    signal = engine.analyze_single_game_by_teams(home, away, sport)

    if signal:
        print_signal(signal)
    else:
        print(f"  Could not find game: {away} @ {home}")
        print("  Check team names match what's in the database.")


def run_schedule(sport: str):
    """Show today's schedule with lines for a sport."""
    from data_ingestion.official.schedule_engine import ScheduleEngine
    engine = ScheduleEngine()
    print(f"\n{'='*60}")
    print(f"  {sport} SCHEDULE — Loading from OddsAPI...")
    print(f"{'='*60}")
    # First save games from OddsAPI to DB
    engine.save_games_from_odds(sport)
    games = engine.get_todays_games(sport)
    if not games:
        print(f"  No {sport} games found for today.")
        # Show upcoming instead
        upcoming = engine.fetch_upcoming_games(sport)[:5]
        if upcoming:
            print(f"\n  Next {len(upcoming)} upcoming {sport} games:")
            for g in upcoming:
                line = f"  {g['away_team']} @ {g['home_team']} — {g['game_time_et']}"
                if g.get("spread") is not None:
                    line += f" | Spread {g['spread']:+.1f} | O/U {g.get('total','?')}"
                print(line)
        return
    print(f"\n  {len(games)} games today:\n")
    for g in games:
        print(f"  {g['away_team']} @ {g['home_team']}")
        print(f"  Time: {g['game_time_et']}")
        if g.get("spread") is not None:
            print(f"  Spread: {g['spread']:+.1f} | Total: {g.get('total','?')}")
        if g.get("home_ml"):
            print(f"  ML: Home {g['home_ml']:+d} | Away {g['away_ml']:+d}")
        print()


def run_brief(home: str, away: str, sport: str):
    """Run a complete pre-game brief for a specific matchup."""
    from analysis.news_analyzer import NewsAnalyzer
    analyzer = NewsAnalyzer()
    print(f"\n{'='*60}")
    print(f"  PRE-GAME BRIEF: {away} @ {home} ({sport})")
    print(f"{'='*60}\n")
    brief = analyzer.get_game_brief(home, away, sport)
    print(brief)


def main():
    parser = argparse.ArgumentParser(description="Sports Betting AI Analysis Engine")
    parser.add_argument("--news", action="store_true",
                       help="Run news analysis with auto schedule lookup")
    parser.add_argument("--sport", type=str,
                       help=f"Sport: NBA / NFL / MLB / NHL")
    parser.add_argument("--schedule", action="store_true",
                       help="Show today's schedule with lines (requires --sport)")
    parser.add_argument("--brief", nargs=2, metavar=("HOME", "AWAY"),
                       help="Pre-game brief: --brief 'Mariners' 'Yankees' --sport MLB")
    parser.add_argument("--game", nargs=2, metavar=("HOME", "AWAY"),
                       help="Full AI analysis: --game 'Lakers' 'Celtics' --sport NBA")
    parser.add_argument("--all", action="store_true",
                       help="Run full analysis across all sports")

    args = parser.parse_args()

    if not any([args.news, args.sport, args.game, args.all,
                args.schedule, args.brief]):
        print("Running news analysis (default)...")
        print("Other options: --schedule --sport MLB | --brief 'Mariners' 'Yankees' --sport MLB\n")
        run_news_analysis()
        return

    if args.schedule:
        if not args.sport:
            print("--schedule requires --sport. Example: --schedule --sport MLB")
            return
        run_schedule(args.sport.upper())

    if args.brief:
        if not args.sport:
            print("--brief requires --sport. Example: --brief 'Mariners' 'Yankees' --sport MLB")
            return
        home, away = args.brief
        run_brief(home, away, args.sport.upper())

    if args.news:
        run_news_analysis()

    if args.sport and not args.schedule and not args.brief:
        sport = args.sport.upper()
        if sport not in SUPPORTED_SPORTS:
            print(f"Unknown sport: {sport}. Choose from: {SUPPORTED_SPORTS}")
            return
        run_game_analysis(sport)

    if args.game:
        if not args.sport:
            print("--game requires --sport.")
            return
        home, away = args.game
        run_specific_game(home, away, args.sport.upper())

    if args.all:
        run_news_analysis()
        for sport in SUPPORTED_SPORTS:
            run_game_analysis(sport)


if __name__ == "__main__":
    main()
