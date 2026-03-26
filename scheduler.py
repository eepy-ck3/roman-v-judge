"""
scheduler.py — Weekly report cron job via APScheduler

Runs inside the FastAPI process (BackgroundScheduler).
Every Monday at 8 AM ET: pull stats, build report, send email + SMS.

Why APScheduler in-process vs a separate cron?
- Simpler to deploy (one process on Render/Railway)
- No separate worker dyno needed
- Persists across deploys if the server stays alive
- Downside: restarts reset the schedule timer (but APScheduler reregisters on startup)
"""
import logging
from datetime import date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="America/New_York")


def start_scheduler():
    """Register the weekly job and start the scheduler. Call once on app startup."""
    _scheduler.add_job(
        weekly_report_job,
        CronTrigger(
            day_of_week=config.WEEKLY_REPORT_DAY,
            hour=config.WEEKLY_REPORT_HOUR,
            minute=config.WEEKLY_REPORT_MINUTE,
            timezone="America/New_York",
        ),
        id="weekly_report",
        replace_existing=True,
        misfire_grace_time=3600,   # If the server was down, run within 1 hour of scheduled time
    )
    _scheduler.start()
    logger.info(
        f"Scheduler started — weekly report fires every {config.WEEKLY_REPORT_DAY.capitalize()} "
        f"at {config.WEEKLY_REPORT_HOUR:02d}:{config.WEEKLY_REPORT_MINUTE:02d} ET"
    )


def stop_scheduler():
    """Gracefully stop the scheduler on app shutdown."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def trigger_report_now():
    """
    Manually trigger the weekly report right now.
    Useful for testing via the /api/trigger-report endpoint.
    """
    logger.info("Manual report trigger requested")
    weekly_report_job()


def weekly_report_job():
    """
    The main weekly report job.
    Pulls all stats, calculates the week/season winner, and sends notifications.
    """
    logger.info("🏃 Running weekly report job...")

    # Import here to avoid circular imports at module load time
    from mlb_api import get_season_stats, get_weekly_stats, get_game_log
    from fangraphs_api import get_both_advanced_stats
    from odds import get_mvp_odds
    from notifications import send_weekly_email, send_weekly_sms, generate_trash_talk
    from scoring import calculate_bet_score

    try:
        # Fetch all the data
        roman_id = config.ROMAN_PLAYER_ID
        judge_id = config.JUDGE_PLAYER_ID

        roman_season = get_season_stats(roman_id) or {}
        judge_season = get_season_stats(judge_id) or {}
        roman_week = get_weekly_stats(roman_id, days=7) or {}
        judge_week = get_weekly_stats(judge_id, days=7) or {}
        fg_stats = get_both_advanced_stats()
        current_odds = get_mvp_odds()

        # Merge FanGraphs advanced stats into season stats
        if fg_stats.get("roman"):
            roman_season.update({
                "war": fg_stats["roman"].get("war"),
                "fwar": fg_stats["roman"].get("war"),
                "wrc_plus": fg_stats["roman"].get("wrc_plus"),
                "woba": fg_stats["roman"].get("woba"),
            })
        if fg_stats.get("judge"):
            judge_season.update({
                "war": fg_stats["judge"].get("war"),
                "fwar": fg_stats["judge"].get("war"),
                "wrc_plus": fg_stats["judge"].get("wrc_plus"),
                "woba": fg_stats["judge"].get("woba"),
            })

        # Calculate who's winning
        season_score = calculate_bet_score(judge_season, roman_season)
        week_score = calculate_bet_score(judge_week, roman_week)

        season_leader = _determine_leader(season_score["judge"], season_score["roman"])
        week_winner = _determine_leader(week_score["judge"], week_score["roman"])

        trash_talk = generate_trash_talk(season_leader)

        # Build the week_of string for the prior Mon-Sun
        today = date.today()
        last_monday = today - timedelta(days=today.weekday() + 7)
        last_sunday = last_monday + timedelta(days=6)
        week_of = f"{last_monday.strftime('%b %d')} – {last_sunday.strftime('%b %d')}"

        report_data = {
            "week_of": week_of,
            "season": config.SEASON,
            "roman": {
                "name": config.ROMAN_DISPLAY_NAME,
                "team_color": config.ROMAN_TEAM_COLOR,
                "season_stats": roman_season,
                "fwar": roman_season.get("fwar"),
                "wrc_plus": roman_season.get("wrc_plus"),
            },
            "judge": {
                "name": config.JUDGE_DISPLAY_NAME,
                "team_color": config.JUDGE_TEAM_COLOR,
                "season_stats": judge_season,
                "fwar": judge_season.get("fwar"),
                "wrc_plus": judge_season.get("wrc_plus"),
            },
            "roman_week": roman_week,
            "judge_week": judge_week,
            "odds": current_odds,
            "score": season_score,
            "week_winner": week_winner,
            "season_leader": season_leader,
            "trash_talk": trash_talk,
            "your_name": config.YOUR_NAME,
            "brother_name": config.BROTHER_NAME,
        }

        # Fire off the notifications
        email_ok = send_weekly_email(report_data)
        sms_ok = send_weekly_sms(report_data)

        logger.info(
            f"Weekly report complete — Email: {'✅' if email_ok else '❌'} | "
            f"SMS: {'✅' if sms_ok else '❌'} | "
            f"Season leader: {season_leader}"
        )

    except Exception as e:
        logger.exception(f"Weekly report job FAILED: {e}")


def _determine_leader(judge_score: int, roman_score: int) -> str:
    """Return 'judge', 'roman', or 'tied' based on scores."""
    if abs(judge_score - roman_score) <= 2:
        return "tied"
    return "judge" if judge_score > roman_score else "roman"
