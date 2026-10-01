"""
data_ingestion/official/book_lines.py

Focused FanDuel + PrizePicks line fetching for the Game Analysis / TD tracker.
Reuses the existing NFLPropsLines client (its _get + credit tracking + event
cache), but keeps PER-BOOK lines (the base parser merges books) and limits to
the markets that matter, to keep credit use low.

Cost model (The Odds API): credits = (unique markets returned) × (regions).
FanDuel is region `us`, PrizePicks is region `us_dfs`, so both books = 2 regions.
With 3 markets that's ~6 credits per game — and we cache per event id, so the
analysis and the TD board share one fetch.
"""

import re
from loguru import logger

from data_ingestion.official.nfl_props_lines import NFLPropsLines, NFL_KEY

FOCUS_MARKETS = ["player_rush_yds", "player_receptions", "player_anytime_td"]
FOCUS_BOOKS = ["fanduel", "prizepicks"]

_US_BOOKS = {"fanduel", "draftkings", "betmgm", "caesars", "pointsbetus"}
_DFS_BOOKS = {"prizepicks", "underdog"}

_client = None


def get_client():
    global _client
    if _client is None:
        _client = NFLPropsLines()
    return _client


def _norm(name):
    s = (name or "").lower()
    s = re.sub(r"[.'`]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def find_event_id(away_team, home_team):
    """Match our game to an OddsAPI event id (free — events endpoint is 0 credits)."""
    c = get_client()
    evs = c.get_events_today()
    for ev in evs:
        if ev.get("home_team") == home_team and ev.get("away_team") == away_team:
            return ev.get("id")
    nick = lambda n: (n or "").split()[-1].lower()
    for ev in evs:
        if nick(ev.get("home_team")) == nick(home_team) and \
           nick(ev.get("away_team")) == nick(away_team):
            return ev.get("id")
    return None


def _parse_by_book(data):
    """player -> market -> {book: {line, over, under}} (keeps books separate)."""
    out = {}
    for book in data.get("bookmakers", []):
        bk = book.get("key", "")
        for market in book.get("markets", []):
            mkey = market.get("key", "").replace("_alternate", "")
            for o in market.get("outcomes", []):
                player = o.get("description", "")
                point = o.get("point")
                nm = (o.get("name", "") or "").lower()
                price = o.get("price")
                if mkey == "player_anytime_td":
                    point = 0.5
                if not player or point is None:
                    continue
                side = "over" if nm in ("over", "yes") else "under"
                d = out.setdefault(player, {}).setdefault(mkey, {}).setdefault(
                    bk, {"line": point})
                d[side] = price
                d["line"] = point
    return out


def fetch_focus_lines(event_id, markets=None, books=None):
    """FanDuel + PrizePicks lines for the focus markets. Cached per event id."""
    markets = markets or FOCUS_MARKETS
    books = books or FOCUS_BOOKS
    c = get_client()
    ck = f"bybook_{event_id}"
    if ck in c._event_cache:
        return c._event_cache[ck]
    regions = []
    if any(b in _US_BOOKS for b in books):
        regions.append("us")
    if any(b in _DFS_BOOKS for b in books):
        regions.append("us_dfs")
    try:
        data = c._get(
            f"sports/{NFL_KEY}/events/{event_id}/odds",
            params={"regions": ",".join(regions),
                    "markets": ",".join(markets),
                    "oddsFormat": "american",
                    "bookmakers": ",".join(books)})
    except Exception as e:
        logger.error(f"[BookLines] fetch failed for {event_id}: {e}")
        return {}
    parsed = _parse_by_book(data)
    c._event_cache[ck] = parsed
    return parsed


def _find_player(by_book, player_name):
    """Match our player name to an OddsAPI player key (normalized)."""
    target = _norm(player_name)
    if not target:
        return None
    for p in by_book:
        if _norm(p) == target:
            return p
    # last-name + first-initial fallback
    tparts = target.split()
    for p in by_book:
        np = _norm(p).split()
        if np and tparts and np[-1] == tparts[-1] and np[0][:1] == tparts[0][:1]:
            return p
    return None


MARKET_FROM_LABEL = [
    ("rush yard", "player_rush_yds"),
    ("reception", "player_receptions"),
    ("rec yard", "player_reception_yds"),
    ("receiving yard", "player_reception_yds"),
    ("pass yard", "player_pass_yds"),
    ("anytime", "player_anytime_td"),
    ("touchdown", "player_anytime_td"),
]


def market_from_prop(prop_label):
    s = (prop_label or "").lower()
    for k, v in MARKET_FROM_LABEL:
        if k in s:
            return v
    return None


def american_to_prob(odds):
    if odds is None:
        return None
    try:
        odds = float(odds)
    except Exception:
        return None
    return 100.0 / (odds + 100.0) if odds > 0 else (-odds) / (-odds + 100.0)


def line_str_for(by_book, player_name, market):
    """'FD o42.5 (-112) · PP 44.5' for a player+market, or '' if no line."""
    pk = _find_player(by_book, player_name)
    if not pk:
        return ""
    md = by_book.get(pk, {}).get(market)
    if not md:
        return ""
    parts = []
    for bk, label in (("fanduel", "FD"), ("prizepicks", "PP")):
        if bk in md:
            ln = md[bk].get("line")
            ov = md[bk].get("over")
            if market == "player_anytime_td":
                p = american_to_prob(ov)
                parts.append(f"{label} TD {ov:+d} ({p*100:.0f}%)" if ov is not None
                             else f"{label} TD")
            else:
                parts.append(f"{label} {ln:g}" + (f" (o {ov:+d})" if ov is not None else ""))
    return " · ".join(parts)


def anytime_td_market(by_book, player_name):
    """Return (fd_odds, fd_implied_prob, pp_present) for a player's anytime TD."""
    pk = _find_player(by_book, player_name)
    if not pk:
        return None, None, False
    md = by_book.get(pk, {}).get("player_anytime_td")
    if not md:
        return None, None, False
    fd = md.get("fanduel", {})
    fd_odds = fd.get("over")
    return fd_odds, american_to_prob(fd_odds), ("prizepicks" in md)
