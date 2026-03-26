"""
main.py — FastAPI backend for the Roman vs Judge Bet Tracker

Routes:
  GET  /                     → serves the dashboard HTML
  GET  /api/comparison        → full head-to-head data (main dashboard payload)
  GET  /api/schedule/{team}   → upcoming games + recent results
  GET  /api/odds              → MVP odds
  GET  /api/trends/{player}   → season trend data for charts
  GET  /api/gamelog/{player}  → last N games detail
  POST /api/odds/manual       → update manual odds
  POST /api/trigger-report    → manually trigger weekly report (for testing)
  GET  /api/cache-stats       → debugging endpoint
  POST /api/cache/clear       → nuke the cache

Run locally:
  uvicorn main:app --reload --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

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
    """Start the scheduler on boot, stop it on shutdown."""
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

# Serve static files (CSS, JS) from the /static directory
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Dashboard Route ──────────────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
async def dashboard():
    """Serve the dashboard HTML."""
    return FileResponse("static/index.html")


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/comparison")
async def get_comparison():
    """
    The main API endpoint — returns everything the dashboard needs.
    Aggregates: player info, season stats, advanced stats, schedule, odds, bet score.
    Cached at the individual data layer (mlb_api, fangraphs_api, etc.)
    """
    roman_id = config.ROMAN_PLAYER_ID
    judge_id = config.JUDGE_PLAYER_ID

    # Fetch all data in parallel-ish (Python isn't truly async here but it's fast
    # due to caching after the first request)
    roman_info = mlb_api.get_player_info(roman_id) or {}
    judge_info = mlb_api.get_player_info(judge_id) or {}
    roman_season = mlb_api.get_season_stats(roman_id) or {}
    judge_season = mlb_api.get_season_stats(judge_id) or {}
    fg_stats = fangraphs_api.get_both_advanced_stats()
    current_odds = odds_module.get_mvp_odds()

    # Merge FanGraphs data into season stats
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

    # Calculate bet score
    bet_score = scoring.calculate_bet_score(judge_season, roman_season)

    # Recent game logs (last 5 games for display)
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
    Get upcoming + recent schedule for a team.
    team_key: 'roman' or 'judge'
    """
    if team_key == "roman":
        team_id = config.ROMAN_TEAM_ID
        player_name = config.ROMAN_DISPLAY_NAME
    elif team_key == "judge":
        team_id = config.JUDGE_TEAM_ID
        player_name = config.JUDGE_DISPLAY_NAME
    else:
        raise HTTPException(status_code=400, detail="team_key must be 'roman' or 'judge'")

    schedule = mlb_api.get_schedule(team_id)
    return {
        "player": player_name,
        "team_id": team_id,
        **schedule
    }


@app.get("/api/odds")
async def get_odds():
    """Current MVP odds for both players."""
    return odds_module.get_mvp_odds()


@app.get("/api/trends/{player_key}")
async def get_trends(player_key: str):
    """
    Season trend data for charts.
    Returns cumulative OPS, HR, RBI by game date.
    player_key: 'roman' or 'judge'
    """
    if player_key == "roman":
        player_id = config.ROMAN_PLAYER_ID
    elif player_key == "judge":
        player_id = config.JUDGE_PLAYER_ID
    else:
        raise HTTPException(status_code=400, detail="player_key must be 'roman' or 'judge'")

    trend_data = mlb_api.get_cumulative_trend(player_id)
    return {
        "player": player_key,
        "data": trend_data,
    }


@app.get("/api/gamelog/{player_key}")
async def get_gamelog(player_key: str, limit: int = 10):
    """
    Detailed game-by-game log.
    player_key: 'roman' or 'judge'
    limit: number of games to return (default 10)
    """
    if player_key == "roman":
        player_id = config.ROMAN_PLAYER_ID
    elif player_key == "judge":
        player_id = config.JUDGE_PLAYER_ID
    else:
        raise HTTPException(status_code=400, detail="player_key must be 'roman' or 'judge'")

    game_log = mlb_api.get_game_log(player_id)
    return {
        "player": player_key,
        "games": game_log[:limit],
    }


# ─── Manual Update Endpoints ──────────────────────────────────────────────────

class ManualOddsUpdate(BaseModel):
    judge_odds: str   # American format: "+200" or "-150"
    roman_odds: str


@app.post("/api/odds/manual")
async def update_odds_manually(update: ManualOddsUpdate):
    """
    Manually update MVP odds when the API doesn't have them.
    Check any sportsbook (DraftKings, FanDuel) and paste the odds here.
    """
    odds_module.update_manual_odds(update.judge_odds, update.roman_odds)
    return {
        "message": "Odds updated!",
        "judge_odds": update.judge_odds,
        "roman_odds": update.roman_odds,
    }


@app.post("/api/trigger-report")
async def trigger_report(background_tasks: BackgroundTasks):
    """
    Manually trigger the weekly report. Great for testing your email/SMS setup.
    Runs in the background so the request returns immediately.
    """
    from scheduler import trigger_report_now
    background_tasks.add_task(trigger_report_now)
    return {"message": "Weekly report triggered! Check your email and phone in a moment."}


# ─── Debug Endpoints ──────────────────────────────────────────────────────────

@app.get("/api/cache-stats")
async def get_cache_stats():
    """See what's cached and how old it is."""
    return cache_module.stats()


@app.post("/api/cache/clear")
async def clear_cache():
    """Nuke the cache — forces fresh data on next request."""
    cache_module.invalidate()
    return {"message": "Cache cleared. Next requests will hit the APIs fresh."}


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Render.com and load balancers ping this."""
    return {"status": "ok", "season": config.SEASON}
