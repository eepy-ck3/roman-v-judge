"""
odds.py — AL MVP odds via The Odds API (the-odds-api.com)

The Odds API structure for award futures is different from game odds:
- Regular game odds live under sport key "baseball_mlb"
- Season-long awards (MVP, Cy Young, etc.) are listed as their OWN sport entries
  with keys like "baseball_mlb_al_mvp" or similar

Strategy:
1. Fetch all available sports from /v4/sports to discover active award markets
2. For any MLB award sport found, pull odds for our two players
3. Fall back to showing N/A if the market isn't open yet

American odds: +150 = bet $100 to win $150. -200 = bet $200 to win $100.
"""
import requests
import logging
from typing import Optional
from config import ODDS_API_KEY, CACHE_TTL_ODDS
from cache import cached

logger = logging.getLogger(__name__)

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

ROMAN_NAME_VARIANTS = {"roman anthony", "r. anthony", "roman a."}
JUDGE_NAME_VARIANTS = {"aaron judge", "a. judge", "judge"}

# Known sport key patterns for MLB awards (The Odds API naming isn't always consistent)
MLB_AWARD_KEYWORDS = {"mlb", "baseball"}
MVP_KEYWORDS = {"mvp", "award", "most valuable"}


@cached(ttl=CACHE_TTL_ODDS)
def get_mvp_odds() -> dict:
    """
    Fetch AL MVP odds for both players.
    Returns structured odds dict — shows N/A cleanly if market isn't available.
    """
    if not ODDS_API_KEY:
        logger.warning("ODDS_API_KEY not set")
        return _empty_response("No API key configured")

    # Step 1: discover which award markets are currently active
    award_sports = _find_award_sport_keys()
    logger.info(f"Found {len(award_sports)} MLB award markets: {[s['key'] for s in award_sports]}")

    if not award_sports:
        logger.info("No MLB award futures markets active right now")
        return _empty_response("No active futures market")

    # Step 2: pull odds from each award market and look for our players
    all_outcomes = {}   # name → [price, ...]

    for sport in award_sports:
        sport_key = sport["key"]
        outcomes = _fetch_outright_odds(sport_key)
        for name, prices in outcomes.items():
            if name not in all_outcomes:
                all_outcomes[name] = []
            all_outcomes[name].extend(prices)
        logger.info(f"Sport '{sport_key}': found {len(outcomes)} players")

    if not all_outcomes:
        return _empty_response("Market found but no odds returned")

    # Step 3: match our players by name
    judge_prices = []
    roman_prices = []
    for name, prices in all_outcomes.items():
        name_lower = name.lower()
        if any(v in name_lower for v in JUDGE_NAME_VARIANTS):
            judge_prices.extend(prices)
        if any(v in name_lower for v in ROMAN_NAME_VARIANTS):
            roman_prices.extend(prices)

    logger.info(f"Judge: {len(judge_prices)} price points | Roman: {len(roman_prices)} price points")

    # Build leaderboard from all outcomes
    leaderboard = []
    for name, prices in all_outcomes.items():
        avg = int(sum(prices) / len(prices))
        leaderboard.append({
            "name": name,
            "odds": _fmt(avg),
            "implied_prob": round(_implied(avg), 1),
        })
    leaderboard.sort(key=lambda x: x["implied_prob"], reverse=True)

    def player_entry(prices, fallback_name):
        if not prices:
            return {"odds": "N/A", "implied_prob": None, "source": "odds_api"}
        avg = int(sum(prices) / len(prices))
        return {
            "odds": _fmt(avg),
            "implied_prob": round(_implied(avg), 1),
            "source": "odds_api",
        }

    return {
        "judge": player_entry(judge_prices, "Aaron Judge"),
        "roman": player_entry(roman_prices, "Roman Anthony"),
        "leaderboard": leaderboard[:10],
        "market_status": "active",
    }


def _find_award_sport_keys() -> list[dict]:
    """
    Call /v4/sports to list all active markets, then filter for MLB award futures.
    This is the right way to discover MVP markets — don't hardcode the sport key.
    """
    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports",
            params={"apiKey": ODDS_API_KEY, "all": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        sports = resp.json()

        remaining = resp.headers.get("x-requests-remaining", "?")
        logger.info(f"Odds API: {remaining} requests remaining this month")

        award_sports = []
        for sport in sports:
            key = sport.get("key", "").lower()
            title = sport.get("title", "").lower()
            has_mlb = any(k in key or k in title for k in MLB_AWARD_KEYWORDS)
            has_mvp = any(k in key or k in title for k in MVP_KEYWORDS)
            if has_mlb and has_mvp:
                award_sports.append(sport)
                logger.info(f"Found award market: {sport['key']} — '{sport.get('title')}'")

        return award_sports

    except requests.HTTPError as e:
        logger.error(f"Odds API /sports error: {e.response.status_code} {e.response.text[:200]}")
        return []
    except Exception as e:
        logger.error(f"Odds API /sports exception: {e}")
        return []


def _fetch_outright_odds(sport_key: str) -> dict[str, list[int]]:
    """
    Fetch outright/futures odds for a given sport key.
    Returns {player_name: [price, price, ...]} aggregated across bookmakers.
    """
    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports/{sport_key}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "outrights",
                "oddsFormat": "american",
            },
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json()

        outcomes: dict[str, list[int]] = {}
        for event in events:
            for bookmaker in event.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    for outcome in market.get("outcomes", []):
                        name = outcome.get("name", "")
                        price = outcome.get("price")
                        if name and price is not None:
                            outcomes.setdefault(name, []).append(int(price))

        return outcomes

    except requests.HTTPError as e:
        logger.error(f"Odds API odds fetch error [{sport_key}]: {e.response.status_code}")
        return {}
    except Exception as e:
        logger.error(f"Odds API odds exception [{sport_key}]: {e}")
        return {}


def debug_raw() -> dict:
    """
    Returns raw data from The Odds API for debugging.
    Accessible via GET /api/odds/debug — does NOT use cache.

    Now returns three buckets:
    - mlb_related: anything with 'mlb' or 'baseball' in the key/title
    - award_related: anything with 'award', 'mvp', 'winner', 'cy young' anywhere
                     across ALL 158 sports — catches markets listed outside baseball
    - has_outrights: any active market with has_outrights=true (futures of any kind)
    """
    if not ODDS_API_KEY:
        return {"error": "ODDS_API_KEY not configured"}

    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports",
            params={"apiKey": ODDS_API_KEY, "all": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        all_sports = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")

        award_keywords = {"award", "mvp", "cy young", "winner", "hank aaron", "rookie"}
        mlb_keywords = {"mlb", "baseball"}

        mlb_related = []
        award_related = []
        has_outrights = []

        for s in all_sports:
            key = s.get("key", "").lower()
            title = s.get("title", "").lower()
            combined = key + " " + title

            if any(k in combined for k in mlb_keywords):
                mlb_related.append(s)

            if any(k in combined for k in award_keywords):
                award_related.append(s)

            if s.get("active") and s.get("has_outrights"):
                has_outrights.append({"key": s["key"], "title": s.get("title", "")})

        return {
            "requests_remaining": remaining,
            "total_sports_available": len(all_sports),
            "mlb_related": mlb_related,
            "award_related_anywhere": award_related,
            "all_active_outrights": has_outrights,
            "note": (
                "award_related_anywhere searches ALL 158 sports for mvp/award keywords. "
                "all_active_outrights shows every futures market currently open — "
                "scan these for anything baseball/MVP related."
            )
        }
    except Exception as e:
        return {"error": str(e)}


def _empty_response(reason: str) -> dict:
    return {
        "judge": {"odds": "N/A", "implied_prob": None, "source": "unavailable"},
        "roman": {"odds": "N/A", "implied_prob": None, "source": "unavailable"},
        "leaderboard": [],
        "market_status": reason,
    }


# ─── Math ─────────────────────────────────────────────────────────────────────

def _implied(odds: int) -> float:
    if odds == 0:
        return 0.0
    return (100 / (odds + 100) * 100) if odds > 0 else (abs(odds) / (abs(odds) + 100) * 100)


def _fmt(odds: int) -> str:
    return f"+{odds}" if odds > 0 else str(odds)


def _parse(odds_str: str) -> int:
    try:
        return int(str(odds_str).replace("+", ""))
    except (ValueError, AttributeError):
        return 0
