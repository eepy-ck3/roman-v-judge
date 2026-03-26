"""
odds.py — AL MVP odds for Aaron Judge and Roman Anthony

Sources tried in order:
1. The Odds API (the-odds-api.com) — free tier, 500 req/month
   Covers MLB futures if the market is active. Caches for 6 hours so
   you'll use maybe 20-30 requests/month total.
2. Manual fallback — update MANUAL_JUDGE_ODDS / MANUAL_ROMAN_ODDS in .env
   This is the reliable fallback. MVP futures aren't always tradeable
   in the API, especially early in the season.

American odds format: +150 means bet $100 to win $150. -200 means bet $200 to win $100.
Implied probability: positive odds → 100/(odds+100). Negative → abs(odds)/(abs(odds)+100).

⚠️ MVP futures markets close or suspend during the season.
   The manual fallback is your best friend here.
"""
import requests
import logging
from typing import Optional
from config import (
    ODDS_API_KEY, MANUAL_JUDGE_ODDS, MANUAL_ROMAN_ODDS,
    ROMAN_DISPLAY_NAME, JUDGE_DISPLAY_NAME, CACHE_TTL_ODDS
)
from cache import cached

logger = logging.getLogger(__name__)

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Odds API sport keys to try for MVP futures
# The actual key changes — "americanfootball_nfl" → "baseball_mlb"
MLB_SPORT_KEY = "baseball_mlb"

# Known name variations on sportsbooks for our players
ROMAN_NAME_VARIANTS = {"roman anthony", "r. anthony"}
JUDGE_NAME_VARIANTS = {"aaron judge", "a. judge"}

_manual_odds = {
    "judge": MANUAL_JUDGE_ODDS,
    "roman": MANUAL_ROMAN_ODDS,
}


@cached(ttl=CACHE_TTL_ODDS)
def get_mvp_odds() -> dict:
    """
    Returns MVP odds for both players.
    Tries The Odds API first, falls back to manual if unavailable.

    Returns:
        {
            "judge": {"odds": "+150", "implied_prob": 40.0, "source": "odds_api"},
            "roman": {"odds": "+2500", "implied_prob": 3.8, "source": "manual"},
            "leaderboard": [{"name": "...", "odds": "...", "implied_prob": ...}, ...]
        }
    """
    if ODDS_API_KEY:
        result = _fetch_from_odds_api()
        if result:
            return result

    # Fall back to manual odds
    logger.info("Using manual MVP odds fallback")
    return _build_manual_odds_response()


def update_manual_odds(judge_odds: str, roman_odds: str):
    """
    Update the manual odds (called from the dashboard's manual update endpoint).
    These persist for the session — restart to reset to .env values.
    """
    _manual_odds["judge"] = judge_odds
    _manual_odds["roman"] = roman_odds
    from cache import invalidate
    invalidate("get_mvp_odds")
    logger.info(f"Manual odds updated — Judge: {judge_odds}, Roman: {roman_odds}")


def _fetch_from_odds_api() -> Optional[dict]:
    """
    Hit The Odds API for MLB MVP futures.
    Free tier: 500 requests/month. With 6h caching, that's ~120 requests/month.
    """
    try:
        # First check available markets — MVP futures might be under "awards" or "outrights"
        resp = requests.get(
            f"{ODDS_API_BASE}/sports/{MLB_SPORT_KEY}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "outrights",   # season-long futures
                "oddsFormat": "american",
                "bookmakers": "draftkings,fanduel,betmgm",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # Log remaining quota
        remaining = resp.headers.get("x-requests-remaining", "?")
        logger.info(f"Odds API: {remaining} requests remaining this month")

        return _parse_odds_api_response(data)

    except requests.HTTPError as e:
        if e.response.status_code == 422:
            logger.info("Odds API: outrights market not available right now — using manual fallback")
        elif e.response.status_code == 401:
            logger.error("Odds API: invalid API key")
        else:
            logger.error(f"Odds API HTTP error: {e}")
        return None
    except Exception as e:
        logger.error(f"Odds API error: {e}")
        return None


def _parse_odds_api_response(data: list) -> Optional[dict]:
    """
    Parse Odds API response. Looks for AL MVP awards market across all events.
    The structure: list of events, each with bookmakers → markets → outcomes.
    """
    # Flatten all outcomes from all events that look like MVP markets
    judge_odds_list = []
    roman_odds_list = []
    leaderboard_map = {}

    for event in data:
        title = event.get("sport_title", "") + event.get("home_team", "")
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")
                if "mvp" not in market_key.lower() and "award" not in market_key.lower():
                    continue

                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    price = outcome.get("price", 0)

                    # Build leaderboard
                    if outcome["name"] not in leaderboard_map:
                        leaderboard_map[outcome["name"]] = []
                    leaderboard_map[outcome["name"]].append(price)

                    if any(v in name for v in JUDGE_NAME_VARIANTS):
                        judge_odds_list.append(price)
                    elif any(v in name for v in ROMAN_NAME_VARIANTS):
                        roman_odds_list.append(price)

    if not judge_odds_list and not roman_odds_list:
        logger.info("Odds API: no MVP market found in response")
        return None

    # Average the odds across bookmakers (simple consensus)
    judge_odds = _format_american(
        int(sum(judge_odds_list) / len(judge_odds_list)) if judge_odds_list else None
    )
    roman_odds = _format_american(
        int(sum(roman_odds_list) / len(roman_odds_list)) if roman_odds_list else None
    )

    # Build leaderboard: average odds per player, sorted by probability
    leaderboard = []
    for name, prices in leaderboard_map.items():
        avg_price = int(sum(prices) / len(prices))
        leaderboard.append({
            "name": name,
            "odds": _format_american(avg_price),
            "implied_prob": round(_american_to_implied_prob(avg_price), 1),
        })
    leaderboard.sort(key=lambda x: x["implied_prob"], reverse=True)

    return {
        "judge": {
            "odds": judge_odds or _manual_odds["judge"],
            "implied_prob": round(_american_to_implied_prob(_parse_american(judge_odds or _manual_odds["judge"])), 1),
            "source": "odds_api" if judge_odds else "manual",
        },
        "roman": {
            "odds": roman_odds or _manual_odds["roman"],
            "implied_prob": round(_american_to_implied_prob(_parse_american(roman_odds or _manual_odds["roman"])), 1),
            "source": "odds_api" if roman_odds else "manual",
        },
        "leaderboard": leaderboard[:10],
    }


def _build_manual_odds_response() -> dict:
    """Build the standard response structure from manual odds."""
    j_odds = _manual_odds["judge"]
    r_odds = _manual_odds["roman"]
    return {
        "judge": {
            "odds": j_odds,
            "implied_prob": round(_american_to_implied_prob(_parse_american(j_odds)), 1),
            "source": "manual",
        },
        "roman": {
            "odds": r_odds,
            "implied_prob": round(_american_to_implied_prob(_parse_american(r_odds)), 1),
            "source": "manual",
        },
        "leaderboard": [],   # Can't build a full leaderboard from manual data
    }


# ─── Odds Math ────────────────────────────────────────────────────────────────

def _american_to_implied_prob(odds: int) -> float:
    """Convert American odds integer to implied probability percentage."""
    if odds == 0:
        return 0.0
    if odds > 0:
        return 100 / (odds + 100) * 100
    else:
        return abs(odds) / (abs(odds) + 100) * 100


def _parse_american(odds_str: str) -> int:
    """Parse '+150' or '-200' string to integer."""
    try:
        return int(odds_str.replace("+", ""))
    except (ValueError, AttributeError):
        return 0


def _format_american(odds: Optional[int]) -> Optional[str]:
    """Format integer odds to '+150' or '-200' string."""
    if odds is None:
        return None
    return f"+{odds}" if odds > 0 else str(odds)
