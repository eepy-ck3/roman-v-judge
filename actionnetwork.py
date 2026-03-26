"""
actionnetwork.py — Attempt to pull AL MVP odds from Action Network's internal API

Action Network (actionnetwork.com) aggregates odds from DraftKings, FanDuel,
BetMGM, Caesars, etc. Their website is a React SPA that loads data from an
internal JSON API — no official docs, but the endpoints are consistent and
don't require auth for public market data.

We try several likely endpoint patterns. The debug_raw() function returns
raw responses from all of them so we can see what's actually available.

Known Action Network API base: https://api.actionnetwork.com/web/v1/
MLB sport_id candidates: trying 2, 3, 4 (differs from their public docs)
"""
import requests
import logging
from typing import Optional
from cache import cached
from config import CACHE_TTL_ODDS

logger = logging.getLogger(__name__)

AN_BASE = "https://api.actionnetwork.com/web/v1"

# Browser headers — Action Network blocks bare requests without a UA
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.actionnetwork.com/",
    "Origin": "https://www.actionnetwork.com",
}

# Player name fragments to match in Action Network responses
JUDGE_NAMES = {"aaron judge", "judge"}
ROMAN_NAMES = {"roman anthony", "anthony"}

# Endpoints to probe — we don't know which one works until we try
CANDIDATE_ENDPOINTS = [
    f"{AN_BASE}/futures?sport=mlb",
    f"{AN_BASE}/futures?league=mlb",
    f"{AN_BASE}/odds?sport=mlb&market_type=futures",
    f"{AN_BASE}/futures?sport_id=2",
    f"{AN_BASE}/futures?sport_id=3",
    f"{AN_BASE}/futures?sport_id=4",
]

REQUEST_TIMEOUT = 10


@cached(ttl=CACHE_TTL_ODDS)
def get_al_mvp_odds() -> Optional[dict]:
    """
    Try Action Network for AL MVP odds.
    Returns structured odds dict or None if unavailable.
    """
    for endpoint in CANDIDATE_ENDPOINTS:
        logger.info(f"Action Network: trying {endpoint}")
        data = _get(endpoint)
        if data is None:
            continue

        result = _parse_for_mvp(data, endpoint)
        if result:
            logger.info(f"Action Network: found MVP odds at {endpoint}")
            return result

    logger.info("Action Network: no AL MVP market found across all candidate endpoints")
    return None


def debug_raw() -> dict:
    """
    Hits every candidate endpoint and returns the raw status + response shape.
    Use via GET /api/odds/debug-an to see what Action Network is returning.
    Does NOT use cache.
    """
    results = []
    for endpoint in CANDIDATE_ENDPOINTS:
        try:
            resp = requests.get(endpoint, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            body = resp.json() if resp.ok else None

            # Summarise the shape without dumping the full response
            shape = _describe_shape(body) if body else None

            results.append({
                "endpoint": endpoint,
                "status": resp.status_code,
                "shape": shape,
                # Show raw body if small enough to be useful
                "preview": _safe_preview(body),
            })
        except Exception as e:
            results.append({
                "endpoint": endpoint,
                "status": "error",
                "error": str(e),
            })

    return {"endpoints_tried": results}


# ─── Parsing ──────────────────────────────────────────────────────────────────

def _parse_for_mvp(data, source_endpoint: str) -> Optional[dict]:
    """
    Walk the response looking for an AL MVP market with our players.
    Action Network response shapes vary by endpoint — handle list and dict roots.
    """
    # Normalise to a list of "market" objects to search through
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # Common keys Action Network wraps responses in
        for key in ("futures", "markets", "odds", "data", "results"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
        if not items:
            items = [data]

    judge_odds = None
    roman_odds = None
    leaderboard = []

    for item in items:
        # Check if this item looks like an MVP market
        title = str(item.get("title", "") or item.get("name", "") or item.get("market_name", "")).lower()
        if not _is_mvp_market(title):
            # Recurse one level — some responses nest markets inside events
            for subkey in ("markets", "outcomes", "odds", "books"):
                sub = item.get(subkey)
                if isinstance(sub, list):
                    sub_result = _parse_for_mvp({subkey: sub}, source_endpoint)
                    if sub_result:
                        return sub_result
            continue

        logger.info(f"Action Network: found candidate market '{title}'")

        # Pull outcomes/runners from this market
        outcomes = (
            item.get("outcomes") or
            item.get("runners") or
            item.get("selections") or
            item.get("participants") or
            []
        )

        for outcome in outcomes:
            name = str(
                outcome.get("name") or
                outcome.get("player_name") or
                outcome.get("label") or ""
            )
            name_lower = name.lower()

            # Get the best available odds (try multiple field names)
            price = _extract_price(outcome)
            if price is None:
                continue

            leaderboard.append({
                "name": name,
                "odds": _fmt(price),
                "implied_prob": round(_implied(price), 1),
            })

            if any(v in name_lower for v in JUDGE_NAMES):
                judge_odds = price
            elif any(v in name_lower for v in ROMAN_NAMES):
                roman_odds = price

    if not leaderboard:
        return None

    leaderboard.sort(key=lambda x: x["implied_prob"], reverse=True)

    def _entry(price):
        if price is None:
            return {"odds": "N/A", "implied_prob": None, "source": "action_network"}
        return {
            "odds": _fmt(price),
            "implied_prob": round(_implied(price), 1),
            "source": "action_network",
        }

    return {
        "judge": _entry(judge_odds),
        "roman": _entry(roman_odds),
        "leaderboard": leaderboard[:10],
        "market_status": "active",
    }


def _is_mvp_market(title: str) -> bool:
    """Return True if the market title looks like an AL MVP award."""
    mvp_signals = {"mvp", "most valuable", "al mvp", "american league mvp"}
    # Exclude NL MVP — we only want AL
    nl_signals = {"nl mvp", "national league mvp"}
    return (
        any(s in title for s in mvp_signals) and
        not any(s in title for s in nl_signals)
    )


def _extract_price(outcome: dict) -> Optional[int]:
    """
    Try every field name Action Network might use for American odds.
    Returns integer odds (e.g. 150, -200) or None.
    """
    for field in ("price", "odds", "american_odds", "money_line", "line", "value", "payout"):
        val = outcome.get(field)
        if val is not None:
            try:
                return int(float(val))
            except (ValueError, TypeError):
                continue

    # Sometimes nested inside a "books" or "odds" array
    for field in ("books", "odds_by_book"):
        books = outcome.get(field)
        if isinstance(books, list) and books:
            val = books[0].get("odds") or books[0].get("price")
            if val is not None:
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    pass

    return None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get(url: str) -> Optional[dict]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        logger.debug(f"Action Network: {url} → {resp.status_code}")
        return None
    except Exception as e:
        logger.debug(f"Action Network: {url} → error: {e}")
        return None


def _describe_shape(data) -> dict:
    """Returns a lightweight description of the response shape for debugging."""
    if isinstance(data, list):
        return {"type": "list", "length": len(data), "first_keys": list(data[0].keys())[:8] if data else []}
    if isinstance(data, dict):
        return {"type": "dict", "keys": list(data.keys())[:12]}
    return {"type": type(data).__name__}


def _safe_preview(data) -> str:
    """First 300 chars of the JSON for quick inspection."""
    import json
    try:
        return json.dumps(data)[:300]
    except Exception:
        return str(data)[:300]


def _implied(odds: int) -> float:
    if odds == 0:
        return 0.0
    return (100 / (odds + 100) * 100) if odds > 0 else (abs(odds) / (abs(odds) + 100) * 100)


def _fmt(odds: int) -> str:
    return f"+{odds}" if odds > 0 else str(odds)
