"""
data_ingestion/official/book_lines.py

Focused FanDuel + PrizePicks line fetching for the Game Analysis / TD tracker.
Reuses the existing NFLPropsLines client (its _get + credit tracking + event
cache), but keeps PER-BOOK, PER-LINE ladders (standard + alternates) so we can
grade the whole ladder (49.5 / 64.5 / 79.5 …), not one safe line.

Cost: credits = (unique markets returned) × (regions). FanDuel=us, PrizePicks=
us_dfs → 2 regions. With rush/receptions standard+alt + anytime_td that's
~5 markets × 2 = ~10 credits/game, cached per event id (analysis + TD share it).
"""

import re
from loguru import logger

from data_ingestion.official.nfl_props_lines import NFLPropsLines, NFL_KEY

# standard + alternate yardage/reception ladders + anytime TD
FOCUS_MARKETS = [
    "player_rush_yds", "player_rush_yds_alternate",
    "player_receptions", "player_receptions_alternate",
    "player_anytime_td",
]
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
    """player -> market -> book -> {point: {line, over, under}} (full ladder)."""
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
                ld = (out.setdefault(player, {}).setdefault(mkey, {})
                      .setdefault(bk, {}).setdefault(point, {"line": point}))
                ld[side] = price
    return out


def fetch_focus_lines(event_id, markets=None, books=None):
    """FanDuel + PrizePicks ladders for the focus markets. Cached per event id."""
    markets = markets or FOCUS_MARKETS
    books = books or FOCUS_BOOKS
    c = get_client()
    ck = f"ladder_{event_id}"
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
    target = _norm(player_name)
    if not target:
        return None
    for p in by_book:
        if _norm(p) == target:
            return p
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


def line_ladder(by_book, player_name, market, book="fanduel"):
    """Sorted list of {line, over, under} for a player+market at one book."""
    pk = _find_player(by_book, player_name)
    if not pk:
        return []
    bd = by_book.get(pk, {}).get(market, {}).get(book, {})
    out = [{"line": ld["line"], "over": ld.get("over"), "under": ld.get("under")}
           for ld in bd.values()]
    out.sort(key=lambda x: x["line"])
    return out


def _main_entry(ladder):
    """The 'main' line = over odds closest to -110 (the central, non-alt line)."""
    best, bestd = None, 1e9
    for e in ladder:
        ov = e.get("over")
        if ov is None:
            continue
        d = abs(float(ov) + 110)
        if d < bestd:
            best, bestd = e, d
    return best or (ladder[len(ladder) // 2] if ladder else None)


def line_str_for(by_book, player_name, market):
    """'FD 64.5 (o -115) · PP 68.5' — the MAIN line per book, for display."""
    parts = []
    for bk, label in (("fanduel", "FD"), ("prizepicks", "PP")):
        lad = line_ladder(by_book, player_name, market, bk)
        if not lad:
            continue
        if market == "player_anytime_td":
            e = lad[0]
            ov = e.get("over")
            p = american_to_prob(ov)
            parts.append(f"{label} TD {int(ov):+d} ({p*100:.0f}%)"
                         if ov is not None else f"{label} TD")
        else:
            e = _main_entry(lad)
            if e:
                ov = e.get("over")
                parts.append(f"{label} {e['line']:g}" +
                             (f" (o {int(ov):+d})" if ov is not None else ""))
    return " · ".join(parts)


def anytime_td_market(by_book, player_name):
    """Return (fd_odds, fd_implied_prob, pp_present) for a player's anytime TD."""
    lad = line_ladder(by_book, player_name, "player_anytime_td", "fanduel")
    pp = bool(line_ladder(by_book, player_name, "player_anytime_td", "prizepicks"))
    if not lad:
        return None, None, pp
    fd_odds = lad[0].get("over")
    return fd_odds, american_to_prob(fd_odds), pp
