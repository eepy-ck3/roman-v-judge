"""
mlb_api.py — Wrapper for the official MLB Stats API (statsapi.mlb.com)

The MLB Stats API is completely free, no API key required, and official.
It's undocumented but well-known in the sabermetrics community.
Docs/community reference: https://github.com/toddrob99/MLB-StatsAPI

Key limitation: WAR and wRC+ are NOT available here — those come from fangraphs_api.py
"""
import requests
import logging
from datetime import datetime, timedelta, date
from typing import Optional
from config import SEASON, CACHE_TTL_STATS, CACHE_TTL_SCHEDULE
from cache import cached

logger = logging.getLogger(__name__)

BASE_URL = "https://statsapi.mlb.com/api/v1"
HEADSHOT_URL = "https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people/{player_id}/headshot/67/current"

# Requests session with a timeout — don't let flaky API responses hang the app
_session = requests.Session()
_session.headers.update({"User-Agent": "RomanVsJudgeBetTracker/1.0"})
REQUEST_TIMEOUT = 10


def _get(endpoint: str, params: dict = None) -> Optional[dict]:
    """Raw GET with error handling. Returns None on failure."""
    url = f"{BASE_URL}{endpoint}"
    try:
        resp = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"MLB API error [{endpoint}]: {e}")
        return None


@cached(ttl=CACHE_TTL_STATS)
def get_player_info(player_id: int) -> Optional[dict]:
    """
    Basic player info: name, position, team, jersey number, headshot.
    Cached for 15 min — this data barely changes.
    """
    data = _get(f"/people/{player_id}", {"hydrate": "currentTeam"})
    if not data or not data.get("people"):
        return None

    p = data["people"][0]
    return {
        "id": p.get("id"),
        "name": p.get("fullName", "Unknown"),
        "first_name": p.get("firstName", ""),
        "last_name": p.get("lastName", ""),
        "position": p.get("primaryPosition", {}).get("abbreviation", ""),
        "jersey_number": p.get("primaryNumber", ""),
        "team": p.get("currentTeam", {}).get("name", ""),
        "team_id": p.get("currentTeam", {}).get("id"),
        "headshot_url": HEADSHOT_URL.format(player_id=player_id),
        "birth_date": p.get("birthDate", ""),
        "bat_side": p.get("batSide", {}).get("description", ""),
        "throw_hand": p.get("pitchHand", {}).get("description", ""),
    }


@cached(ttl=CACHE_TTL_STATS)
def get_season_stats(player_id: int, season: int = None) -> Optional[dict]:
    """
    Full season batting stats from MLB Stats API.
    Returns the stats dict or None if unavailable (e.g., player is in minors).
    """
    s = season or SEASON
    data = _get(f"/people/{player_id}/stats", {
        "stats": "season",
        "season": s,
        "group": "hitting",
        "sportId": 1,  # MLB only, not MiLB
    })

    if not data:
        return None

    # Dig into the nested response structure
    stats_list = data.get("stats", [])
    if not stats_list or not stats_list[0].get("splits"):
        logger.info(f"No season stats for player {player_id} in {s} — might be in minors or pre-debut")
        return _empty_stats()

    raw = stats_list[0]["splits"][0]["stat"]
    return _parse_hitting_stats(raw)


@cached(ttl=CACHE_TTL_STATS)
def get_game_log(player_id: int, season: int = None) -> list[dict]:
    """
    Game-by-game log for the season. Used for:
    - Last 5 game results
    - Weekly stat calculations
    - Building trend chart data

    Returns a list of game dicts, most recent first.
    """
    s = season or SEASON
    data = _get(f"/people/{player_id}/stats", {
        "stats": "gameLog",
        "season": s,
        "group": "hitting",
        "sportId": 1,
    })

    if not data:
        return []

    stats_list = data.get("stats", [])
    if not stats_list or not stats_list[0].get("splits"):
        return []

    games = []
    for split in stats_list[0]["splits"]:
        stat = split.get("stat", {})
        game_date_str = split.get("date", "")
        opponent = split.get("opponent", {}).get("name", "Unknown")
        is_home = split.get("isHome", True)
        team_score = split.get("team", {}).get("score")
        opp_score = split.get("opponent", {}).get("score")

        # Build W/L result string
        result = "—"
        if team_score is not None and opp_score is not None:
            win = team_score > opp_score
            result = f"{'W' if win else 'L'} {team_score}-{opp_score}"

        games.append({
            "date": game_date_str,
            "opponent": opponent,
            "home_away": "vs" if is_home else "@",
            "result": result,
            **_parse_hitting_stats(stat)
        })

    # Most recent first
    games.sort(key=lambda g: g["date"], reverse=True)
    return games


@cached(ttl=CACHE_TTL_SCHEDULE)
def get_schedule(team_id: int, days_ahead: int = 7, days_back: int = 5) -> dict:
    """
    Returns upcoming games and recent results for a team.
    Hydrates with probable pitcher data where available.
    """
    today = date.today()
    start = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    data = _get("/schedule", {
        "teamId": team_id,
        "startDate": start,
        "endDate": end,
        "sportId": 1,
        "hydrate": "probablePitcher,linescore,team",
    })

    if not data:
        return {"upcoming": [], "recent": []}

    upcoming = []
    recent = []
    today_str = today.strftime("%Y-%m-%d")

    for date_entry in data.get("dates", []):
        game_date = date_entry.get("date", "")
        for game in date_entry.get("games", []):
            parsed = _parse_game(game, team_id, game_date)
            if parsed:
                if game_date >= today_str and parsed.get("status") not in ("Final", "Game Over"):
                    upcoming.append(parsed)
                else:
                    recent.append(parsed)

    # Sort and limit
    upcoming.sort(key=lambda g: g["date"])
    recent.sort(key=lambda g: g["date"], reverse=True)

    return {
        "upcoming": upcoming[:5],
        "recent": recent[:5]
    }


def get_weekly_stats(player_id: int, days: int = 7) -> Optional[dict]:
    """
    Calculates accumulated stats for the past `days` days from the game log.
    This is used for the weekly email report.
    """
    game_log = get_game_log(player_id)
    if not game_log:
        return None

    cutoff = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    weekly_games = [g for g in game_log if g.get("date", "") >= cutoff]

    if not weekly_games:
        return _empty_stats()

    # Accumulate counting stats
    totals = {
        "games": len(weekly_games),
        "ab": sum(g.get("ab", 0) for g in weekly_games),
        "hits": sum(g.get("hits", 0) for g in weekly_games),
        "doubles": sum(g.get("doubles", 0) for g in weekly_games),
        "triples": sum(g.get("triples", 0) for g in weekly_games),
        "hr": sum(g.get("hr", 0) for g in weekly_games),
        "rbi": sum(g.get("rbi", 0) for g in weekly_games),
        "runs": sum(g.get("runs", 0) for g in weekly_games),
        "sb": sum(g.get("sb", 0) for g in weekly_games),
        "bb": sum(g.get("bb", 0) for g in weekly_games),
        "k": sum(g.get("k", 0) for g in weekly_games),
    }

    # Recalculate rate stats from totals
    ab = totals["ab"]
    hits = totals["hits"]
    bb = totals["bb"]
    pa = ab + bb + sum(g.get("hbp", 0) for g in weekly_games) + sum(g.get("sf", 0) for g in weekly_games)
    tb = (hits - totals["doubles"] - totals["triples"] - totals["hr"]) + \
         (2 * totals["doubles"]) + (3 * totals["triples"]) + (4 * totals["hr"])

    totals["avg"] = f"{hits/ab:.3f}" if ab > 0 else ".000"
    totals["obp"] = f"{(hits + bb) / pa:.3f}" if pa > 0 else ".000"
    totals["slg"] = f"{tb / ab:.3f}" if ab > 0 else ".000"

    obp_val = float(totals["obp"])
    slg_val = float(totals["slg"])
    totals["ops"] = f"{obp_val + slg_val:.3f}"

    return totals


def get_cumulative_trend(player_id: int) -> list[dict]:
    """
    Builds season-to-date cumulative stats at each game date.
    Powers the trend charts on the dashboard.
    Returns list of {date, ops, hr, rbi, avg, games} dicts.
    """
    game_log = get_game_log(player_id)
    if not game_log:
        return []

    # Reverse to go oldest → newest
    games = list(reversed(game_log))

    cum_ab = cum_hits = cum_doubles = cum_triples = cum_hr = cum_rbi = 0
    cum_bb = cum_tb = cum_runs = 0
    trend = []

    for i, game in enumerate(games):
        cum_ab += game.get("ab", 0)
        cum_hits += game.get("hits", 0)
        cum_doubles += game.get("doubles", 0)
        cum_triples += game.get("triples", 0)
        cum_hr += game.get("hr", 0)
        cum_rbi += game.get("rbi", 0)
        cum_bb += game.get("bb", 0)
        cum_runs += game.get("runs", 0)

        # Total bases
        singles = cum_hits - cum_doubles - cum_triples - cum_hr
        cum_tb = singles + (2 * cum_doubles) + (3 * cum_triples) + (4 * cum_hr)

        pa = cum_ab + cum_bb  # simplified PA
        obp = (cum_hits + cum_bb) / pa if pa > 0 else 0
        slg = cum_tb / cum_ab if cum_ab > 0 else 0
        avg = cum_hits / cum_ab if cum_ab > 0 else 0

        trend.append({
            "date": game["date"],
            "games": i + 1,
            "avg": round(avg, 3),
            "obp": round(obp, 3),
            "slg": round(slg, 3),
            "ops": round(obp + slg, 3),
            "hr": cum_hr,
            "rbi": cum_rbi,
            "runs": cum_runs,
        })

    return trend


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_hitting_stats(raw: dict) -> dict:
    """Normalize a raw MLB Stats API stat dict into our clean format."""
    return {
        "games": raw.get("gamesPlayed", 0),
        "ab": raw.get("atBats", 0),
        "pa": raw.get("plateAppearances", 0),
        "hits": raw.get("hits", 0),
        "doubles": raw.get("doubles", 0),
        "triples": raw.get("triples", 0),
        "hr": raw.get("homeRuns", 0),
        "rbi": raw.get("rbi", 0),
        "runs": raw.get("runs", 0),
        "sb": raw.get("stolenBases", 0),
        "cs": raw.get("caughtStealing", 0),
        "bb": raw.get("baseOnBalls", 0),
        "k": raw.get("strikeOuts", 0),
        "hbp": raw.get("hitByPitch", 0),
        "sf": raw.get("sacFlies", 0),
        "avg": raw.get("avg", ".000"),
        "obp": raw.get("obp", ".000"),
        "slg": raw.get("slg", ".000"),
        "ops": raw.get("ops", ".000"),
        "babip": raw.get("babip", ".000"),
        "tb": raw.get("totalBases", 0),
        # WAR and wRC+ come from FanGraphs, not here
        "war": None,
        "wrc_plus": None,
        "fwar": None,
    }


def _empty_stats() -> dict:
    """All-zeros stats object for players with no MLB data yet."""
    return {
        "games": 0, "ab": 0, "pa": 0, "hits": 0, "doubles": 0, "triples": 0,
        "hr": 0, "rbi": 0, "runs": 0, "sb": 0, "cs": 0, "bb": 0, "k": 0,
        "hbp": 0, "sf": 0, "avg": ".000", "obp": ".000", "slg": ".000",
        "ops": ".000", "babip": ".000", "tb": 0,
        "war": None, "wrc_plus": None, "fwar": None,
    }


def _parse_game(game: dict, team_id: int, game_date: str) -> Optional[dict]:
    """Parse a single game from the schedule API into our format."""
    away_team = game.get("teams", {}).get("away", {})
    home_team = game.get("teams", {}).get("home", {})

    # Figure out which side our team is on
    our_side = "home" if home_team.get("team", {}).get("id") == team_id else "away"
    opp_side = "away" if our_side == "home" else "home"

    our_data = home_team if our_side == "home" else away_team
    opp_data = away_team if our_side == "home" else home_team

    opponent_name = opp_data.get("team", {}).get("teamName", opp_data.get("team", {}).get("name", "TBD"))

    # Probable pitcher for the opposing team (most relevant for the hitter)
    opp_pitcher = opp_data.get("probablePitcher", {}).get("fullName", "TBD")

    # Parse game time from ISO string
    game_time = "TBD"
    raw_time = game.get("gameDate", "")
    if raw_time:
        try:
            dt = datetime.strptime(raw_time, "%Y-%m-%dT%H:%M:%SZ")
            # Convert UTC to ET (rough: -4 or -5 hours)
            # For simplicity we display ET without DST awareness
            from datetime import timezone
            et_hour = (dt.hour - 4) % 24
            am_pm = "AM" if et_hour < 12 else "PM"
            display_hour = et_hour if et_hour <= 12 else et_hour - 12
            if display_hour == 0:
                display_hour = 12
            game_time = f"{display_hour}:{dt.minute:02d} {am_pm} ET"
        except ValueError:
            pass

    # Result for completed games
    linescore = game.get("linescore", {})
    our_score = our_data.get("score")
    opp_score = opp_data.get("score")
    result = None
    if our_score is not None and opp_score is not None:
        win = our_score > opp_score
        result = f"{'W' if win else 'L'} {our_score}-{opp_score}"

    return {
        "date": game_date,
        "time": game_time,
        "home_away": "vs" if our_side == "home" else "@",
        "opponent": opponent_name,
        "opposing_pitcher": opp_pitcher,
        "status": game.get("status", {}).get("detailedState", "Scheduled"),
        "result": result,
        "game_pk": game.get("gamePk"),
    }
