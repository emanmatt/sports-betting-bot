"""
config/settings.py
Central configuration — loads .env and exposes typed settings
used everywhere in the app.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# ── Database ───────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sportsbetting")
REDIS_URL    = os.getenv("REDIS_URL", "redis://localhost:6379")

# ── External API Keys ──────────────────────────────────────────────────────
ODDS_API_KEY          = os.getenv("ODDS_API_KEY", "")
REDDIT_CLIENT_ID      = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET  = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT     = os.getenv("REDDIT_USER_AGENT", "SportsBettingBot/1.0")
TWITTER_BEARER_TOKEN  = os.getenv("TWITTER_BEARER_TOKEN", "")
ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY", "")
AI_PROVIDER           = os.getenv("AI_PROVIDER", "heuristic").lower()  # heuristic / anthropic
AI_MODEL              = os.getenv("AI_MODEL", "claude-3-5-haiku-latest")
X_SEARCH_QUERY_SUFFIX = os.getenv("X_SEARCH_QUERY_SUFFIX", "-is:retweet lang:en")
MIN_EDGE_PROBABILITY  = float(os.getenv("MIN_EDGE_PROBABILITY", "0.54"))
MONTE_CARLO_SIMS      = int(os.getenv("MONTE_CARLO_SIMS", "20000"))
PINECONE_API_KEY      = os.getenv("PINECONE_API_KEY", "")
PINECONE_ENVIRONMENT  = os.getenv("PINECONE_ENVIRONMENT", "")

# ── App Settings ───────────────────────────────────────────────────────────
LOG_LEVEL   = os.getenv("LOG_LEVEL", "INFO")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# ── Sports & League Config ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════
#  ⚙️  SPORTS TOGGLE — EDIT THIS ONE LINE WHEN SEASONS START
# ═══════════════════════════════════════════════════════════════════
#  Right now: MLB only (NBA/NFL/NHL are offseason).
#
#  When NFL starts (Sept 9, 2026):   SUPPORTED_SPORTS = ["MLB", "NFL"]
#  When NBA/NHL start (Oct 20, 2026): SUPPORTED_SPORTS = ["MLB", "NFL", "NBA", "NHL"]
#
#  Just change the line below, save, then push to GitHub:
#    git add config/settings.py
#    git commit -m "Enable [sport]"
#    git push
# ═══════════════════════════════════════════════════════════════════
SUPPORTED_SPORTS = ["MLB"]

# All sports the bot CAN handle (don't edit — used for config lookups)
ALL_SPORTS = ["NBA", "NFL", "MLB", "NHL"]

# OddsAPI sport keys (used in API calls)
ODDS_API_SPORT_KEYS = {
    "NBA": "basketball_nba",
    "NFL": "americanfootball_nfl",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
}

# ESPN API sport/league slugs (used in ESPN endpoints)
ESPN_SPORT_CONFIG = {
    "NBA": {"sport": "basketball",    "league": "nba"},
    "NFL": {"sport": "americanfootball", "league": "nfl"},
    "MLB": {"sport": "baseball",      "league": "mlb"},
    "NHL": {"sport": "hockey",        "league": "nhl"},
}

# Reddit subreddits to monitor per sport
REDDIT_SUBREDDITS = {
    "NBA": ["nba", "nbadiscussion", "basketballgm",
            "lakers", "warriors", "celtics", "heat", "nets",
            "thunder", "nuggets", "bucks", "sixers", "knicks"],
    "NFL": ["nfl", "fantasyfootball",
            "chiefs", "eagles", "cowboys", "patriots",
            "49ers", "packers", "ravens", "bills", "broncos"],
    "MLB": ["baseball", "mlbdiscussion",
            "NYYankees", "dodgers", "redsox", "cubs",
            "braves", "astros", "mets", "cardinals"],
    "NHL": ["hockey", "nhl",
            "leafs", "habs", "rangers", "bruins",
            "penguins", "blackhawks", "avalanche", "oilers"],
}

# Trusted news RSS feeds (beat reporters + major outlets)
RSS_FEEDS = {
    "NBA": [
        "https://www.espn.com/espn/rss/nba/news",
        "https://bleacherreport.com/nba.rss",
        "https://www.rotowire.com/basketball/rss.php",
        "https://basketball.realgm.com/rss/wiretap/0.xml",
    ],
    "NFL": [
        "https://www.espn.com/espn/rss/nfl/news",
        "https://bleacherreport.com/nfl.rss",
        "https://www.rotowire.com/football/rss.php",
    ],
    "MLB": [
        "https://www.espn.com/espn/rss/mlb/news",
        "https://bleacherreport.com/mlb.rss",
        "https://www.rotowire.com/baseball/rss.php",
    ],
    "NHL": [
        "https://www.espn.com/espn/rss/nhl/news",
        "https://bleacherreport.com/nhl.rss",
        "https://www.rotowire.com/hockey/rss.php",
    ],
}

# Contract data scraping targets
CONTRACT_SOURCES = {
    "NBA": {
        "spotrac": "https://www.spotrac.com/nba/contracts/",
        "hoopshype": "https://hoopshype.com/salaries/",
    },
    "NFL": {
        "spotrac": "https://www.spotrac.com/nfl/contracts/",
        "overthecap": "https://overthecap.com/contracts",
    },
    "MLB": {
        "spotrac": "https://www.spotrac.com/mlb/contracts/",
    },
    "NHL": {
        "spotrac": "https://www.spotrac.com/nhl/contracts/",
        "capfriendly": "https://www.capfriendly.com/browse/active/",
    },
}

# Scheduling intervals (in minutes)
SCHEDULE_INTERVALS = {
    "odds_update":     5,    # every 5 min — odds move fast
    "injury_update":  15,    # every 15 min
    "news_update":    30,    # every 30 min
    "reddit_update":  60,    # every hour
    "stats_update":  120,    # every 2 hours
    "contract_update": 1440, # once per day
}
