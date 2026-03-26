"""
fanduel_odds.py — AL MVP odds from FanDuel via their AppSync GraphQL API

FanDuel's internal architecture:
- Pricing is served via AWS AppSync GraphQL at pir.{state}.sportsbook.fanduel.com
- Market: 734.152289006 (AL MVP 2025 — stable all season)
- selectionIds are permanent Betfair-style runner IDs, fixed at market creation

Confirmed selectionId mapping (verified 2025-03-25):
  11604591 → Aaron Judge     (+185 at time of discovery)
  79285407 → Roman Anthony   (+2000 at time of discovery)

The GraphQL endpoint requires an Authorization header with the public API key
embedded in the FanDuel SPA bundle.
"""
import requests
import logging
from typing import Optional
from cache import cached
from config import CACHE_TTL_ODDS

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://pir.nj.sportsbook.fanduel.com/graphql"
API_KEY = "NfxZUKb5R+do8pGKXq27wPTO3JHUlUmn"

# AL MVP 2025 market
MARKET_ID = "734.152289006"

# Permanent selectionId → player name mapping (fixed for life of this market)
JUDGE_SELECTION_ID = 11604591
ROMAN_SELECTION_ID = 79285407

HEADERS = {
    "Authorization": API_KEY,
    "Content-Type": "application/json",
    "Origin": "https://sportsbook.fanduel.com",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

QUERY = """
query GetMarketPrices($ids: [String]!) {
    getMarketPrices(ids: $ids) {
        id
        marketId
        marketStatus
        runnerDetails {
            selectionId
            runnerStatus
            winRunnerOdds {
                americanDisplayOdds {
                    americanOddsInt
                }
            }
        }
    }
}
"""


@cached(ttl=CACHE_TTL_ODDS)
def get_al_mvp_odds() -> Optional[dict]:
    """
    Fetch AL MVP odds from FanDuel GraphQL.
    Returns structured odds dict or None if unavailable.
    """
    try:
        resp = requests.post(
            GRAPHQL_URL,
            headers=HEADERS,
            json={"query": QUERY, "variables": {"ids": [MARKET_ID]}},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        markets = data.get("data", {}).get("getMarketPrices", [])
        if not markets:
            logger.warning("FanDuel: no market data returned")
            return None

        market = markets[0]
        if market.get("marketStatus") not in ("OPEN", "ACTIVE"):
            logger.info(f"FanDuel: market status = {market.get('marketStatus')}")
            return None

        runners = market.get("runnerDetails", [])

        judge_odds = None
        roman_odds = None
        leaderboard_raw = []

        for runner in runners:
            if runner.get("runnerStatus") != "ACTIVE":
                continue
            sel_id = runner.get("selectionId")
            price = (
                runner.get("winRunnerOdds", {})
                .get("americanDisplayOdds", {})
                .get("americanOddsInt")
            )
            if price is None:
                continue

            if sel_id == JUDGE_SELECTION_ID:
                judge_odds = price
            elif sel_id == ROMAN_SELECTION_ID:
                roman_odds = price

            leaderboard_raw.append((sel_id, price))

        if judge_odds is None and roman_odds is None:
            logger.warning("FanDuel: neither player found in runners")
            return None

        leaderboard_raw.sort(key=lambda x: _implied(x[1]), reverse=True)
        leaderboard = [
            {
                "name": _sel_name(sel_id),
                "odds": _fmt(price),
                "implied_prob": round(_implied(price), 1),
            }
            for sel_id, price in leaderboard_raw[:10]
        ]

        def _entry(price):
            if price is None:
                return {"odds": "N/A", "implied_prob": None, "source": "fanduel"}
            return {
                "odds": _fmt(price),
                "implied_prob": round(_implied(price), 1),
                "source": "fanduel",
            }

        logger.info(
            f"FanDuel: Judge={_fmt(judge_odds) if judge_odds else 'N/A'} "
            f"Roman={_fmt(roman_odds) if roman_odds else 'N/A'}"
        )
        return {
            "judge": _entry(judge_odds),
            "roman": _entry(roman_odds),
            "leaderboard": leaderboard,
            "market_status": "active",
        }

    except requests.HTTPError as e:
        logger.error(f"FanDuel GraphQL HTTP error: {e.response.status_code}")
        return None
    except Exception as e:
        logger.error(f"FanDuel GraphQL error: {e}")
        return None


def _sel_name(sel_id: int) -> str:
    if sel_id == JUDGE_SELECTION_ID:
        return "Aaron Judge"
    if sel_id == ROMAN_SELECTION_ID:
        return "Roman Anthony"
    return f"Runner {sel_id}"


def _implied(odds: int) -> float:
    if odds == 0:
        return 0.0
    return (100 / (odds + 100) * 100) if odds > 0 else (abs(odds) / (abs(odds) + 100) * 100)


def _fmt(odds: int) -> str:
    return f"+{odds}" if odds > 0 else str(odds)
