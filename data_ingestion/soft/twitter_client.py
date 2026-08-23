"""X API v2 client. It is optional and returns an empty list when unconfigured."""
from datetime import datetime, timezone
import requests
from config.settings import TWITTER_BEARER_TOKEN, X_SEARCH_QUERY_SUFFIX


class TwitterClient:
    def __init__(self, token=TWITTER_BEARER_TOKEN):
        self.token = token
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    @property
    def enabled(self):
        return bool(self.token)

    def search(self, query, limit=25):
        if not self.enabled:
            return []
        params = {"query": f"{query} {X_SEARCH_QUERY_SUFFIX}", "max_results": min(max(limit, 10), 100),
                  "tweet.fields": "created_at,public_metrics,author_id", "expansions": "author_id",
                  "user.fields": "username,verified"}
        try:
            response = self.session.get("https://api.x.com/2/tweets/search/recent", params=params, timeout=15)
            response.raise_for_status(); payload = response.json()
        except requests.RequestException:
            return []
        users = {u["id"]: u for u in payload.get("includes", {}).get("users", [])}
        return [{"platform": "x", "post_id": t["id"], "content": t.get("text", ""),
                 "author": users.get(t.get("author_id"), {}).get("username", "unknown"),
                 "source_name": "X", "url": f"https://x.com/i/web/status/{t['id']}",
                 "upvotes": t.get("public_metrics", {}).get("like_count", 0),
                 "comments": t.get("public_metrics", {}).get("reply_count", 0),
                 "is_verified_source": bool(users.get(t.get("author_id"), {}).get("verified", False)),
                 "published_at": datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)}
                for t in payload.get("data", [])]
