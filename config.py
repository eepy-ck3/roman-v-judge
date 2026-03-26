"""
config.py — All the knobs you need to twist.
Loads from .env (or real environment variables on the server).
Change this file, not the API code.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Player IDs ────────────────────────────────────────────────────────────────
# MLB Stats API player IDs — verify at:
#   statsapi.mlb.com/api/v1/people/search?names=Roman+Anthony
#   statsapi.mlb.com/api/v1/people/search?names=Aaron+Judge
ROMAN_PLAYER_ID = int(os.getenv("ROMAN_PLAYER_ID", "701350"))   # Roman Anthony ✅ confirmed
JUDGE_PLAYER_ID = int(os.getenv("JUDGE_PLAYER_ID", "592450"))   # Aaron Judge ✅ confirmed

# MLB team IDs for schedule lookups
ROMAN_TEAM_ID = int(os.getenv("ROMAN_TEAM_ID", "111"))   # Boston Red Sox
JUDGE_TEAM_ID = int(os.getenv("JUDGE_TEAM_ID", "147"))   # New York Yankees

# FanGraphs player IDs (for WAR + wRC+ — different ID system than MLB)
# Find yours: go to fangraphs.com/players/roman-anthony and check the URL for ?playerid=
# Aaron Judge confirmed: fangraphs.com/players/aaron-judge/15640/stats → 15640
# ⚠️ If the FG ID is wrong, fWAR/wRC+ show N/A but the app still works fine
#    (bet score auto-falls back to basic weights using MLB Stats API data only)
ROMAN_FANGRAPHS_ID = os.getenv("ROMAN_FANGRAPHS_ID", "sa934320")   # ⚠️ verify at fangraphs.com
JUDGE_FANGRAPHS_ID = os.getenv("JUDGE_FANGRAPHS_ID", "15640")       # ✅ confirmed

SEASON = int(os.getenv("SEASON", "2025"))

# ─── Player Display Names & Team Colors ───────────────────────────────────────
ROMAN_DISPLAY_NAME = os.getenv("ROMAN_DISPLAY_NAME", "Roman Anthony")
JUDGE_DISPLAY_NAME = os.getenv("JUDGE_DISPLAY_NAME", "Aaron Judge")
ROMAN_TEAM_COLOR = os.getenv("ROMAN_TEAM_COLOR", "#BD3039")   # Red Sox red
JUDGE_TEAM_COLOR = os.getenv("JUDGE_TEAM_COLOR", "#003087")   # Yankees navy

# ─── Notification Recipients ───────────────────────────────────────────────────
YOUR_NAME = os.getenv("YOUR_NAME", "Cole")
BROTHER_NAME = os.getenv("BROTHER_NAME", "Roman")   # Or whatever his name is

YOUR_EMAIL = os.getenv("YOUR_EMAIL", "")
BROTHER_EMAIL = os.getenv("BROTHER_EMAIL", "")
YOUR_PHONE = os.getenv("YOUR_PHONE", "")      # E.164 format: +15551234567
BROTHER_PHONE = os.getenv("BROTHER_PHONE", "")

# ─── Twilio — SMS ─────────────────────────────────────────────────────────────
# Sign up free at twilio.com — get ~$15 trial credit, ~$0.008/SMS after
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")   # Your Twilio number

# ─── Email — Gmail SMTP ───────────────────────────────────────────────────────
# Use a Gmail App Password (not your real password):
#   myaccount.google.com → Security → 2FA → App Passwords
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")   # Gmail App Password
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Roman vs Judge Bet Tracker 🏆")

# ─── Anthropic — Weekly Narrative ─────────────────────────────────────────────
# Used to generate a Jeff Passan-style write-up in the Monday email.
# Get a key at console.anthropic.com — the weekly call costs ~$0.05.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ─── The Odds API — MVP Futures ───────────────────────────────────────────────
# Free tier at the-odds-api.com — 500 requests/month is plenty with caching
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

# Manual fallback odds (American format: +200, -150, etc.)
# Update these whenever you check a sportsbook. Used when API key is missing
# or the futures market isn't available in the API response.
MANUAL_JUDGE_ODDS = os.getenv("MANUAL_JUDGE_ODDS", "+150")
MANUAL_ROMAN_ODDS = os.getenv("MANUAL_ROMAN_ODDS", "+2500")

# ─── App Settings ─────────────────────────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
PORT = int(os.getenv("PORT", "8000"))

# How long to cache API responses (seconds). 15 min is a good balance.
# MLB data updates ~every 10 min during games, hourly otherwise.
CACHE_TTL_STATS = int(os.getenv("CACHE_TTL_STATS", "900"))      # 15 min
CACHE_TTL_SCHEDULE = int(os.getenv("CACHE_TTL_SCHEDULE", "3600"))  # 1 hour
CACHE_TTL_ODDS = int(os.getenv("CACHE_TTL_ODDS", "21600"))      # 6 hours

# Scheduler — when to send the weekly report (cron format, Eastern time)
# Default: Monday at 8:00 AM ET
WEEKLY_REPORT_DAY = os.getenv("WEEKLY_REPORT_DAY", "mon")
WEEKLY_REPORT_HOUR = int(os.getenv("WEEKLY_REPORT_HOUR", "8"))
WEEKLY_REPORT_MINUTE = int(os.getenv("WEEKLY_REPORT_MINUTE", "0"))
