"""
data_ingestion/soft/reddit_client.py
Monitors Reddit for breaking news, rumors, locker room chatter,
injury whispers, and game-day reports across all 4 sports.

Uses PRAW (Python Reddit API Wrapper) — completely free.
Sign up at: https://www.reddit.com/prefs/apps (create "script" app)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import praw
from datetime import datetime, timezone
from loguru import logger
from database.models import get_session, SocialPost
from config.settings import (
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
    REDDIT_USER_AGENT, REDDIT_SUBREDDITS, SUPPORTED_SPORTS
)

# Flair/keywords that signal high betting relevance
HIGH_IMPACT_KEYWORDS = [
    "injury", "injured", "out", "doubtful", "questionable", "dnp",
    "did not practice", "limited", "game-time decision", "gtd",
    "suspended", "ejected", "trade", "lineup", "scratch", "healthy scratch",
    "starting", "starter", "rest", "load management", "back to back",
    "illness", "flu", "personal reasons", "family emergency",
]

# Known beat reporters / verified sources to prioritize
VERIFIED_BEAT_REPORTERS = {
    "nba": ["ShamsCharania", "adrianwoj", "ChrisBHaynes", "KeithSmithNBA",
            "jonkrawczynski", "IanBogard", "wojespn"],
    "nfl": ["AdamSchefter", "RapSheet", "TomPelissero", "MikeGarafolo",
            "JayGlazer", "CharlesRobinson"],
    "mlb": ["JonHeyman", "KenRosenthal", "MarkFeinsand", "MLBNetwork"],
    "nhl": ["PierreVLeBrun", "ElliottFriedman", "FrankSeravalli"],
}


class RedditClient:
    """Scrapes Reddit for sports betting-relevant information."""

    def __init__(self):
        if not REDDIT_CLIENT_ID:
            logger.warning("[Reddit] No Reddit credentials set. Add to .env file.")
            self.reddit = None
            return

        self.reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
            read_only=True,  # We only read, never post
        )
        logger.info("[Reddit] ✅ Connected to Reddit API.")

    def _assess_betting_impact(self, content: str) -> tuple[str, list[str]]:
        """
        Analyze a post to determine its betting relevance.
        Returns (impact_level, matched_keywords)
        """
        content_lower = content.lower()
        matched = [kw for kw in HIGH_IMPACT_KEYWORDS if kw in content_lower]

        if len(matched) >= 3:
            return "high", matched
        elif len(matched) >= 1:
            return "medium", matched
        else:
            return "none", []

    def _is_verified_source(self, author: str, sport: str) -> bool:
        """Check if the author is a known beat reporter."""
        sport_lower = sport.lower()
        reporters = VERIFIED_BEAT_REPORTERS.get(sport_lower, [])
        return author.lower() in [r.lower() for r in reporters]

    def fetch_subreddit_posts(self, subreddit_name: str, sport: str,
                               limit: int = 50) -> list[dict]:
        """Fetch recent hot posts from a subreddit."""
        if not self.reddit:
            return []

        try:
            subreddit = self.reddit.subreddit(subreddit_name)
            posts = []

            for submission in subreddit.hot(limit=limit):
                # Skip posts older than 24 hours
                post_time = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
                age_hours = (datetime.now(tz=timezone.utc) - post_time).total_seconds() / 3600
                if age_hours > 24:
                    continue

                content = f"{submission.title} {submission.selftext}"
                impact, keywords = self._assess_betting_impact(content)
                is_verified = self._is_verified_source(str(submission.author), sport)

                # Boost priority for verified reporters regardless of keyword match
                if is_verified:
                    impact = "high"

                posts.append({
                    "sport":            sport,
                    "platform":         "reddit",
                    "source_name":      f"r/{subreddit_name}",
                    "post_id":          f"reddit_{submission.id}",
                    "author":           str(submission.author),
                    "content":          content[:2000],  # Trim to 2000 chars
                    "url":              f"https://reddit.com{submission.permalink}",
                    "upvotes":          submission.score,
                    "comments":         submission.num_comments,
                    "is_verified_source": is_verified,
                    "relevance_tags":   keywords,
                    "betting_impact":   impact,
                    "published_at":     post_time.replace(tzinfo=None),
                    "captured_at":      datetime.utcnow(),
                })

            return posts

        except Exception as e:
            logger.warning(f"[Reddit] Error fetching r/{subreddit_name}: {e}")
            return []

    def fetch_comments_from_post(self, submission_id: str, sport: str,
                                  limit: int = 20) -> list[dict]:
        """
        Fetch top comments from a specific post.
        Useful for injury posts where comments have more detail.
        """
        if not self.reddit:
            return []

        try:
            submission = self.reddit.submission(id=submission_id)
            submission.comments.replace_more(limit=0)
            comments = []

            for comment in submission.comments[:limit]:
                impact, keywords = self._assess_betting_impact(comment.body)
                is_verified = self._is_verified_source(str(comment.author), sport)

                if impact != "none" or is_verified:
                    comments.append({
                        "sport":            sport,
                        "platform":         "reddit",
                        "source_name":      f"r/{submission.subreddit.display_name}",
                        "post_id":          f"reddit_comment_{comment.id}",
                        "author":           str(comment.author),
                        "content":          comment.body[:2000],
                        "url":              f"https://reddit.com{comment.permalink}",
                        "upvotes":          comment.score,
                        "comments":         0,
                        "is_verified_source": is_verified,
                        "relevance_tags":   keywords,
                        "betting_impact":   impact,
                        "published_at":     datetime.fromtimestamp(comment.created_utc),
                        "captured_at":      datetime.utcnow(),
                    })
            return comments
        except Exception as e:
            logger.warning(f"[Reddit] Error fetching comments for {submission_id}: {e}")
            return []

    def fetch_sport_reddit(self, sport: str) -> list[dict]:
        """Fetch posts from all subreddits for a sport."""
        subreddits = REDDIT_SUBREDDITS.get(sport, [])
        all_posts = []

        for sub in subreddits:
            posts = self.fetch_subreddit_posts(sub, sport, limit=30)
            all_posts.extend(posts)
            logger.debug(f"[Reddit] r/{sub}: {len(posts)} relevant posts")

        # Also search for high-impact posts across all posts
        high_impact = [p for p in all_posts if p["betting_impact"] == "high"]
        logger.info(f"[Reddit] {sport}: {len(all_posts)} total posts, "
                    f"{len(high_impact)} high-impact.")
        return all_posts

    def save_posts(self, sport: str):
        """Fetch and save Reddit posts for a sport."""
        db = get_session()
        try:
            posts = self.fetch_sport_reddit(sport)
            saved = skipped = 0

            for post in posts:
                # Skip if already saved
                existing = db.query(SocialPost).filter_by(
                    post_id=post["post_id"]
                ).first()
                if existing:
                    # Update upvote count (can change over time)
                    existing.upvotes = post["upvotes"]
                    existing.comments = post["comments"]
                    skipped += 1
                    continue

                db.add(SocialPost(**post))
                saved += 1

            db.commit()
            logger.info(f"[Reddit] ✅ {sport}: {saved} new posts saved, "
                        f"{skipped} already in DB.")
        except Exception as e:
            db.rollback()
            logger.error(f"[Reddit] Failed to save {sport} posts: {e}")
        finally:
            db.close()

    def get_breaking_news(self, sport: str, hours: int = 2) -> list[dict]:
        """
        Get only the most recent high-impact posts.
        Called right before analysis to get the freshest info.
        """
        db = get_session()
        try:
            from sqlalchemy import text
            cutoff = datetime.utcnow().replace(
                hour=datetime.utcnow().hour - hours
            )
            posts = (db.query(SocialPost)
                     .filter(
                         SocialPost.sport == sport,
                         SocialPost.platform == "reddit",
                         SocialPost.betting_impact.in_(["high", "medium"]),
                         SocialPost.published_at >= cutoff,
                     )
                     .order_by(SocialPost.upvotes.desc())
                     .limit(20)
                     .all())
            return posts
        finally:
            db.close()

    def run_all_sports(self):
        """Pull Reddit data for all sports."""
        for sport in SUPPORTED_SPORTS:
            self.save_posts(sport)


if __name__ == "__main__":
    client = RedditClient()
    client.run_all_sports()
