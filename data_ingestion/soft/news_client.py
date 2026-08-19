"""
data_ingestion/soft/news_client.py
Pulls from RSS feeds: ESPN, Rotowire, Bleacher Report, and beat writer blogs.
Also scrapes full article text when needed.
100% free — no API key required.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from email.utils import parsedate_to_datetime
from loguru import logger
from database.models import get_session, NewsArticle
from config.settings import RSS_FEEDS, SUPPORTED_SPORTS

# Keywords that flag betting relevance in headlines
BETTING_RELEVANT_KEYWORDS = [
    "injury", "injured", "out", "doubtful", "questionable", "suspended",
    "trade", "waived", "cut", "signed", "lineup", "start", "starter",
    "illness", "personal", "rest", "load management", "return",
    "cleared", "ruled out", "game-time", "practice", "limited",
    "benched", "inactive", "IR", "reserve",
]

# Source trust levels for weighting analysis
SOURCE_TRUST = {
    "rotowire.com":        10,  # Highest trust for injury/lineup
    "rotoworld":           10,
    "espn.com":             8,
    "theringer.com":        7,
    "theathletic.com":      9,
    "bleacherreport.com":   6,
    "nba.com":             10,
    "nfl.com":             10,
    "mlb.com":             10,
    "nhl.com":             10,
}


class NewsClient:
    """Scrapes RSS feeds and news sources for betting-relevant sports news."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; SportsBettingBot/1.0)",
        })

    def _parse_date(self, date_str: str) -> datetime:
        """Parse various date formats from RSS feeds."""
        if not date_str:
            return datetime.utcnow()
        try:
            return parsedate_to_datetime(date_str).replace(tzinfo=None)
        except Exception:
            try:
                return datetime.fromisoformat(date_str.replace("Z", ""))
            except Exception:
                return datetime.utcnow()

    def _get_source_name(self, url: str) -> str:
        """Extract clean source name from URL."""
        for domain, _ in SOURCE_TRUST.items():
            if domain in url:
                return domain
        return url.split("/")[2] if "//" in url else url[:50]

    def _assess_impact(self, title: str, content: str) -> tuple[str, list[str]]:
        """Assess the betting impact of an article."""
        combined = f"{title} {content}".lower()
        matched = [kw for kw in BETTING_RELEVANT_KEYWORDS if kw in combined]

        if len(matched) >= 3 or any(kw in title.lower() for kw in
                                     ["out", "injured", "suspended", "ruled out", "doubtful"]):
            return "high", matched
        elif len(matched) >= 1:
            return "medium", matched
        return "low", matched

    def fetch_rss_feed(self, feed_url: str, sport: str) -> list[dict]:
        """Parse a single RSS feed and return articles."""
        try:
            feed = feedparser.parse(feed_url)
            articles = []
            source = self._get_source_name(feed_url)

            for entry in feed.entries[:20]:  # Last 20 articles per feed
                title   = entry.get("title", "")
                content = entry.get("summary", entry.get("description", ""))
                url     = entry.get("link", "")
                pub_date = self._parse_date(entry.get("published", ""))

                # Skip articles older than 48 hours
                age_hours = (datetime.utcnow() - pub_date).total_seconds() / 3600
                if age_hours > 48:
                    continue

                impact, keywords = self._assess_impact(title, content)

                articles.append({
                    "sport":            sport,
                    "source":           source,
                    "title":            title[:500],
                    "content":          content[:3000],
                    "url":              url[:1000],
                    "published_at":     pub_date,
                    "relevance_tags":   keywords,
                    "betting_impact":   impact,
                    "captured_at":      datetime.utcnow(),
                })

            return articles

        except Exception as e:
            logger.warning(f"[News] RSS parse failed for {feed_url}: {e}")
            return []

    def fetch_full_article(self, url: str) -> str:
        """
        Scrape the full text of an article.
        Called when RSS summary is insufficient.
        """
        try:
            resp = self.session.get(url, timeout=10)
            soup = BeautifulSoup(resp.content, "lxml")

            # Remove nav, ads, scripts
            for tag in soup(["script", "style", "nav", "footer",
                              "header", "aside", "iframe"]):
                tag.decompose()

            # Find main content
            main = (soup.find("article") or
                    soup.find("div", class_="article-body") or
                    soup.find("div", class_="story-body") or
                    soup.find("main"))

            if main:
                return main.get_text(separator=" ", strip=True)[:5000]
            return soup.get_text(separator=" ", strip=True)[:5000]

        except Exception as e:
            logger.debug(f"[News] Full article scrape failed: {e}")
            return ""

    def fetch_sport_news(self, sport: str) -> list[dict]:
        """Fetch all RSS feeds for a sport."""
        feeds = RSS_FEEDS.get(sport, [])
        all_articles = []

        for feed_url in feeds:
            articles = self.fetch_rss_feed(feed_url, sport)
            all_articles.extend(articles)
            logger.debug(f"[News] {feed_url}: {len(articles)} recent articles")

        # Deduplicate by URL
        seen = set()
        unique = []
        for a in all_articles:
            if a["url"] not in seen:
                seen.add(a["url"])
                unique.append(a)

        high_impact = [a for a in unique if a["betting_impact"] == "high"]
        logger.info(f"[News] {sport}: {len(unique)} unique articles, "
                    f"{len(high_impact)} high-impact.")
        return unique

    def save_news(self, sport: str):
        """Fetch and save news articles for a sport."""
        db = get_session()
        try:
            articles = self.fetch_sport_news(sport)
            saved = skipped = 0

            for article in articles:
                existing = db.query(NewsArticle).filter_by(
                    url=article["url"]
                ).first()
                if existing:
                    skipped += 1
                    continue

                # For high-impact articles, try to get full text
                if article["betting_impact"] == "high" and article["url"]:
                    full_text = self.fetch_full_article(article["url"])
                    if full_text:
                        article["content"] = full_text

                db.add(NewsArticle(**article))
                saved += 1

            db.commit()
            logger.info(f"[News] ✅ {sport}: {saved} new articles saved, "
                        f"{skipped} already in DB.")
        except Exception as e:
            db.rollback()
            logger.error(f"[News] Failed to save {sport} articles: {e}")
        finally:
            db.close()

    def get_recent_high_impact(self, sport: str, hours: int = 6) -> list[NewsArticle]:
        """Get high-impact news from the last N hours for pre-game analysis."""
        db = get_session()
        try:
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            return (db.query(NewsArticle)
                    .filter(
                        NewsArticle.sport == sport,
                        NewsArticle.betting_impact.in_(["high", "medium"]),
                        NewsArticle.published_at >= cutoff,
                    )
                    .order_by(NewsArticle.published_at.desc())
                    .limit(30)
                    .all())
        finally:
            db.close()

    def run_all_sports(self):
        """Pull news for all sports."""
        for sport in SUPPORTED_SPORTS:
            self.save_news(sport)


if __name__ == "__main__":
    client = NewsClient()
    client.run_all_sports()
