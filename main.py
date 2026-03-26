"""
main.py — FastAPI backend for the Roman vs Judge Bet Tracker

Routes:
  GET  /                     → serves the dashboard HTML
  GET  /api/comparison        → full head-to-head data (main dashboard payload)
  GET  /api/schedule/{team}   → upcoming games with career vs. pitcher stats
  GET  /api/odds              → MVP odds
  GET  /api/trends/{player}   → season trend data for charts
  GET  /api/gamelog/{player}  → last N games detail (powers "Last 5 Games" panel)
  POST /api/odds/refresh      → bust odds cache and re-fetch
  GET  /api/odds/debug        → inspect raw Odds API response
  POST /api/trigger-report    → manually trigger weekly report
  GET  /api/cache-stats       → debugging endpoint
  POST /api/cache/clear       → nuke the cache

Run locally:
  uvicorn main:app --reload --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import config
import mlb_api
import fangraphs_api
import odds as odds_module
import cache as cache_module
import scoring

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ─── App Lifecycle ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    from scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    logger.info("🚀 Roman vs Judge Bet Tracker is live!")
    yield
    stop_scheduler()
    logger.info("👋 Shutting down.")


app = FastAPI(
    title="Roman vs Judge Bet Tracker",
    description="The definitive answer to who's winning this bet.",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
async def dashboard():
    return FileResponse("static/index.html")


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/comparison")
async def get_comparison():
    """
    Main dashboard payload — player info, season stats, advanced stats, odds, bet score.
    recent_games here powers the separate "Last 5 Games" panel (not the schedule panel).
    """
    roman_id = config.ROMAN_PLAYER_ID
    judge_id = config.JUDGE_PLAYER_ID

    roman_info = mlb_api.get_player_info(roman_id) or {}
    judge_info = mlb_api.get_player_info(judge_id) or {}
    roman_season = mlb_api.get_season_stats(roman_id) or {}
    judge_season = mlb_api.get_season_stats(judge_id) or {}
    fg_stats = fangraphs_api.get_both_advanced_stats()
    current_odds = odds_module.get_mvp_odds()

    if fg_stats.get("roman"):
        roman_season.update({
            "fwar": fg_stats["roman"].get("war"),
            "wrc_plus": fg_stats["roman"].get("wrc_plus"),
            "woba": fg_stats["roman"].get("woba"),
            "iso": fg_stats["roman"].get("iso"),
            "bb_pct": fg_stats["roman"].get("bb_pct"),
            "k_pct": fg_stats["roman"].get("k_pct"),
            "off": fg_stats["roman"].get("off"),
            "def_runs": fg_stats["roman"].get("def_runs"),
        })
    if fg_stats.get("judge"):
        judge_season.update({
            "fwar": fg_stats["judge"].get("war"),
            "wrc_plus": fg_stats["judge"].get("wrc_plus"),
            "woba": fg_stats["judge"].get("woba"),
            "iso": fg_stats["judge"].get("iso"),
            "bb_pct": fg_stats["judge"].get("bb_pct"),
            "k_pct": fg_stats["judge"].get("k_pct"),
            "off": fg_stats["judge"].get("off"),
            "def_runs": fg_stats["judge"].get("def_runs"),
        })

    bet_score = scoring.calculate_bet_score(judge_season, roman_season)

    # Powers the "Last 5 Games" panel — separate from the schedule panel
    roman_gamelog = mlb_api.get_game_log(roman_id)[:5]
    judge_gamelog = mlb_api.get_game_log(judge_id)[:5]

    return {
        "roman": {
            "info": roman_info,
            "season_stats": roman_season,
            "recent_games": roman_gamelog,
            "player_id": roman_id,
        },
        "judge": {
            "info": judge_info,
            "season_stats": judge_season,
            "recent_games": judge_gamelog,
            "player_id": judge_id,
        },
        "odds": current_odds,
        "bet_score": bet_score,
        "season": config.SEASON,
        "team_colors": {
            "roman": config.ROMAN_TEAM_COLOR,
            "judge": config.JUDGE_TEAM_COLOR,
        }
    }


@app.get("/api/schedule/{team_key}")
async def get_schedule(team_key: str):
    """
    Upcoming games for a team, enriched with career batter vs. pitcher stats.

    NEW: For each upcoming game with an announced starter, fetches the batter's
    career stats against that specific pitcher via the MLB vsPlayer endpoint.
    Cached at the same TTL as schedule data (1 hour).

    EDIT 2: 'recent' results removed — schedule now shows upcoming games only.
    Recent game stats live in /api/gamelog/{player} (powers the Last 5 Games panel).
    """
    if team_key == "roman":
        team_id = config.ROMAN_TEAM_ID
        player_id = config.ROMAN_PLAYER_ID
        player_name = config.ROMAN_DISPLAY_NAME
    elif team_key == "judge":
        team_id = config.JUDGE_TEAM_ID
        player_id = config.JUDGE_PLAYER_ID
        player_name = config.JUDGE_DISPLAY_NAME
    else:
        raise HTTPException(status_code=400, detail="team_key must be 'roman' or 'judge'")

    schedule = mlb_api.get_schedule(team_id)

    # NEW: Career vs. Pitcher stats — enrich each upcoming game server-side.
    # Skips games where no starter has been announced (opposing_pitcher_id is None).
    # Roman Anthony will return None for most pitchers as a 2025 rookie — expected.
    for game in schedule["upcoming"]:
        pitcher_id = game.get("opposing_pitcher_id")
        if pitcher_id:
            game["career_vs_pitcher"] = mlb_api.get_career_vs_pitcher(player_id, pitcher_id)
        else:
            game["career_vs_pitcher"] = None

    return {
        "player": player_name,
        "team_id": team_id,
        **schedule,
    }


@app.get("/api/odds")
async def get_odds():
    """Current AL MVP odds for both players."""
    return odds_module.get_mvp_odds()


@app.get("/api/trends/{player_key}")
async def get_trends(player_key: str):
    """Season-to-date cumulative stats for trend charts."""
    if player_key == "roman":
        player_id = config.ROMAN_PLAYER_ID
    elif player_key == "judge":
        player_id = config.JUDGE_PLAYER_ID
    else:
        raise HTTPException(status_code=400, detail="player_key must be 'roman' or 'judge'")

    return {"player": player_key, "data": mlb_api.get_cumulative_trend(player_id)}


@app.get("/api/gamelog/{player_key}")
async def get_gamelog(player_key: str, limit: int = 10):
    """
    Game-by-game log. Powers the "Last 5 Games" panel on the dashboard
    and is used by the weekly report for per-game stats.
    """
    if player_key == "roman":
        player_id = config.ROMAN_PLAYER_ID
    elif player_key == "judge":
        player_id = config.JUDGE_PLAYER_ID
    else:
        raise HTTPException(status_code=400, detail="player_key must be 'roman' or 'judge'")

    return {"player": player_key, "games": mlb_api.get_game_log(player_id)[:limit]}


# ─── Odds Endpoints ───────────────────────────────────────────────────────────

@app.post("/api/odds/refresh")
async def refresh_odds():
    """Bust the odds cache and fetch fresh data from The Odds API."""
    cache_module.invalidate("get_mvp_odds")
    return odds_module.get_mvp_odds()


@app.get("/api/odds/debug")
async def debug_odds():
    """Raw Odds API response — use to confirm which MLB markets are active."""
    return odds_module.debug_raw()


# ─── Admin / Debug ────────────────────────────────────────────────────────────

@app.post("/api/trigger-report")
async def trigger_report(background_tasks: BackgroundTasks):
    """Manually send the weekly report. Useful for testing email/SMS setup."""
    from scheduler import trigger_report_now
    background_tasks.add_task(trigger_report_now)
    return {"message": "Weekly report triggered! Check your email and phone in a moment."}


@app.get("/api/cache-stats")
async def get_cache_stats():
    return cache_module.stats()


@app.post("/api/cache/clear")
async def clear_cache():
    cache_module.invalidate()
    return {"message": "Cache cleared."}


@app.get("/health")
async def health():
    return {"status": "ok", "season": config.SEASON}
