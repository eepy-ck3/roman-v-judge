"""
fangraphs_api.py — Unofficial FanGraphs API for WAR and wRC+

FanGraphs doesn't have a public API, but their leaderboard page
loads data from a JSON endpoint that's consistent enough to use.

Why FanGraphs for WAR/wRC+?
- MLB Stats API doesn't provide WAR (it's proprietary to FG/BR)
- wRC+ (park/league adjusted offense) is the gold standard offensive metric
- fWAR (FanGraphs WAR) factors in defense and baserunning — critical for MVP voters

⚠️ Unofficial API — FanGraphs could change it anytime.
   If it breaks, the app falls back to None and displays "N/A".
   Manual update endpoint: POST /api/manual-war to set values.
"""
import requests
import logging
from typing import Optional
from config import ROMAN_FANGRAPHS_ID, JUDGE_FANGRAPHS_ID, SEASON, CACHE_TTL_STATS
from cache import cached

logger = logging.getLogger(__name__)

# FanGraphs leaderboard API — returns all qualified hitters
FG_LEADERBOARD_URL = "https://www.fangraphs.com/api/leaders/major-league/data"

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; RomanVsJudgeBetTracker/1.0)",
    "Referer": "https://www.fangraphs.com/leaders.aspx",
})
REQUEST_TIMEOUT = 15


@cached(ttl=CACHE_TTL_STATS)
def get_advanced_stats(fangraphs_id: str, season: int = None) -> Optional[dict]:
    """
    Fetch WAR, wRC+, and other advanced stats for a single player from FanGraphs.
    Type 8 = standard advanced stats (includes WAR, wRC+, BABIP, etc.)
    """
    s = season or SEASON
    params = {
        "age": "",
        "pos": "all",
        "stats": "bat",
        "lg": "all",
        "qual": 0,            # Include players below the plate appearance threshold
        "season": s,
        "season1": s,
        "startdate": "",
        "enddate": "",
        "month": 0,
        "hand": "",
        "team": 0,
        "pageitems": 2000,    # Get everyone, filter client-side
        "pagenum": 1,
        "ind": 0,             # Combined stats (not split by team)
        "rost": 0,
        "players": "",
        "type": 8,            # Advanced stats table
        "postseason": "",
        "sortdir": "default",
        "sortstat": "WAR",
    }

    try:
        resp = _session.get(FG_LEADERBOARD_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"FanGraphs API error: {e}")
        return None
    except ValueError as e:
        logger.error(f"FanGraphs JSON parse error: {e}")
        return None

    # The response has a 'data' array of player rows
    players = data.get("data", [])
    if not players:
        logger.warning("FanGraphs returned empty data")
        return None

    # Find our player by FanGraphs playerid
    # FG IDs can be numeric or prefixed (e.g., "sa934320" for prospects)
    for player in players:
        if str(player.get("playerid", "")) == str(fangraphs_id):
            return _parse_fg_stats(player)

    logger.warning(f"FanGraphs: player {fangraphs_id} not found in leaderboard")
    return None


@cached(ttl=CACHE_TTL_STATS)
def get_both_advanced_stats() -> dict:
    """
    Fetches FanGraphs data for both players in a single API call.
    More efficient than two separate calls since we hit the same endpoint.
    """
    s = SEASON
    params = {
        "pos": "all", "stats": "bat", "lg": "all", "qual": 0,
        "season": s, "season1": s, "month": 0, "team": 0,
        "pageitems": 2000, "pagenum": 1, "ind": 0, "type": 8,
    }

    try:
        resp = _session.get(FG_LEADERBOARD_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"FanGraphs combined fetch error: {e}")
        return {"roman": None, "judge": None}

    players = data.get("data", [])
    roman_stats = None
    judge_stats = None

    for player in players:
        pid = str(player.get("playerid", ""))
        if pid == str(ROMAN_FANGRAPHS_ID):
            roman_stats = _parse_fg_stats(player)
        elif pid == str(JUDGE_FANGRAPHS_ID):
            judge_stats = _parse_fg_stats(player)

    if not roman_stats:
        logger.info(f"FanGraphs: Roman Anthony ({ROMAN_FANGRAPHS_ID}) not found — might be pre-debut or ID changed")
    if not judge_stats:
        logger.info(f"FanGraphs: Aaron Judge ({JUDGE_FANGRAPHS_ID}) not found")

    return {"roman": roman_stats, "judge": judge_stats}


def _parse_fg_stats(player: dict) -> dict:
    """
    Map FanGraphs column names to our internal format.
    Column names in the FG API are a bit cryptic.
    """
    # FanGraphs uses these column names in type=8 response:
    # WAR, wRC+, BABIP, BB%, K%, ISO, wOBA, Off, Def, BsR
    return {
        "name": player.get("PlayerName", player.get("Name", "")),
        "team": player.get("Team", ""),
        "games": player.get("G", 0),
        "pa": player.get("PA", 0),
        "war": player.get("WAR"),           # fWAR
        "wrc_plus": player.get("wRC+"),     # park/league adjusted runs created
        "woba": player.get("wOBA"),         # weighted on-base average
        "babip": player.get("BABIP"),
        "iso": player.get("ISO"),           # isolated power (SLG - AVG)
        "bb_pct": player.get("BB%"),        # walk rate
        "k_pct": player.get("K%"),          # strikeout rate
        "off": player.get("Off"),           # offensive runs above average
        "def_runs": player.get("Def"),      # defensive runs above average
        "bsr": player.get("BsR"),           # baserunning runs above average
        "hr": player.get("HR", 0),
        "avg": player.get("AVG"),
        "obp": player.get("OBP"),
        "slg": player.get("SLG"),
        "ops": player.get("OPS"),
    }
