# ⚾ Roman vs. Judge Bet Tracker

> A season-long, trash-talk-enabled, auto-reporting dashboard to settle the greatest debate of our time: **Roman Anthony or Aaron Judge for AL MVP?**

Live dashboard + weekly email/SMS reports. Deployed in about 15 minutes.

---

## What This Does

**Dashboard** (updates every 5 min)
- Head-to-head stat comparison: AVG, OBP, SLG, OPS, HR, RBI, Runs, SB, WAR, wRC+, and more
- Visual indicators showing who leads each category
- "Bet Score" — a weighted MVP-style formula showing who's winning the bet overall
- Upcoming schedule (next 5 games) with opposing starting pitcher
- Last 5 game results for each player
- AL MVP odds from The Odds API (with manual fallback)
- Season trend charts (OPS, HR, AVG, RBI over time)

**Weekly Report** (every Monday 8 AM ET)
- Email with a clean HTML stat summary (team colors, comparison table, trash talk)
- SMS with a concise text version
- Auto-generated trash talk line based on who's leading

---

## Architecture

```
Browser ─────────────────────────────────────────────────────────────
    │  GET /          → index.html (static)
    │  GET /api/*     → FastAPI routes
    └──────────────────────────────────────────────────────────────────
                              │
                         FastAPI (main.py)
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
    mlb_api.py         fangraphs_api.py        odds.py
    (official MLB       (WAR, wRC+)         (The Odds API
    Stats API,           unofficial            + manual
    free, no key)        endpoint)             fallback)
          │
    cache.py (in-memory TTL cache — 15min stats, 6hr odds)
          │
    APScheduler ──→ scheduler.py ──→ notifications.py
    (weekly cron)      (builds           (Gmail SMTP + Twilio SMS)
                       report data)
```

**Stack choices explained:**
- **FastAPI** over Flask: built-in async, auto-docs at `/docs`, modern Python
- **Vanilla JS** over React: zero build step, nothing to update or break
- **MLB Stats API**: completely free, official, no key required
- **FanGraphs unofficial API**: only place to get fWAR and wRC+ programmatically
- **APScheduler in-process**: simpler than a separate worker, no extra Render dyno
- **Gmail SMTP**: free, no third-party email service needed
- **Render.com free tier**: 750 free hours/month — more than enough for one app

---

## Quick Start (Local)

### 1. Clone & install

```bash
git clone <your-repo-url>
cd roman-vs-judge
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Now edit .env with your values — see the section below for details
```

### 3. Run it

```bash
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` — that's it. The dashboard should load.

> **First run note:** The server hits the MLB API and FanGraphs on first load. If Roman Anthony hasn't been called up yet or the season hasn't started, you'll see all zeros — that's expected.

---

## Configuration Guide

Open `.env` and fill these in:

### Player IDs (most important)

**⚠️ Verify Roman Anthony's MLB ID before deploying.** He's a prospect, his ID might differ.

To look up an MLB player ID:
```bash
# In your browser:
https://statsapi.mlb.com/api/v1/people/search?names=Roman+Anthony
https://statsapi.mlb.com/api/v1/people/search?names=Aaron+Judge
```
Look for `"id"` in the response. Aaron Judge is definitely `592450`.

For FanGraphs IDs:
1. Go to `fangraphs.com/players/{first-name}-{last-name}`
2. Look at the URL — it'll have `?playerid=XXXXX` or similar
3. Aaron Judge = `15640`, Roman Anthony = look up manually

### Gmail App Password (Email)

Regular Gmail passwords won't work — you need an App Password:
1. Go to `myaccount.google.com`
2. Security → 2-Step Verification → App Passwords
3. Create one named "Bet Tracker" (or whatever)
4. Copy the 16-character password into `SMTP_PASSWORD`

### Twilio (SMS)

1. Sign up at `twilio.com` — get ~$15 free trial credit
2. Verify your phone number and your brother's phone number in the Twilio console
3. Buy a phone number (~$1/month or use free trial number)
4. Copy Account SID, Auth Token, and your Twilio number into `.env`
5. Each SMS costs ~$0.008 — two texts/week = ~$0.83/month

**Phone numbers must be in E.164 format: `+15551234567`**

### Odds API (MVP Futures)

1. Sign up at `the-odds-api.com` — free tier = 500 requests/month
2. With 6-hour caching, you'll use ~20 requests/month — well within free tier
3. Copy your API key into `ODDS_API_KEY`

**If you skip this:** The dashboard still works — it just shows the manual odds you set in `.env` or update via the dashboard. MVP futures aren't always available in the API anyway (the market opens and closes). The manual update button on the dashboard is your friend.

---

## Deployment (Render.com)

### Option A: One-click from GitHub (recommended)

1. Push your code to a GitHub repo (make sure `.env` is NOT committed — it's in `.gitignore`)
2. Go to `dashboard.render.com` → New → Web Service
3. Connect your repo
4. Render auto-detects Python. Set build command: `pip install -r requirements.txt`
5. Set start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. **Add all your environment variables** in the Render dashboard (Settings → Environment)
7. Deploy!

### Option B: Railway

```bash
npm install -g @railway/cli
railway login
railway init
railway up
railway variables set ROMAN_PLAYER_ID=694302  # etc for all vars
```

### Free tier note

Render's free tier **sleeps after 15 minutes of inactivity** — first request after sleep takes ~30 seconds. For a personal dashboard this is fine. If it bothers you, use Railway ($5/month) or Render's $7/month paid tier.

**The scheduler still fires when the app is sleeping** — no wait, that's wrong. The scheduler IS in-process, so if Render spins down the app, the Monday morning report might not fire.

**Fix for free tier:** Use a free cron ping service like `cron-job.org` to hit your `/health` endpoint every 10 minutes. This keeps the app awake. Add a cronjob there for free.

---

## Manual Odds Updates

Since MVP futures aren't always available programmatically, update them from the dashboard:

1. Check DraftKings, FanDuel, or BetMGM for "AL MVP" odds
2. Go to your dashboard → MVP Race → manual update form
3. Enter odds in American format (`+200`, `-150`, etc.)
4. Hit Update — it takes effect immediately

Or update via the API:
```bash
curl -X POST http://localhost:8000/api/odds/manual \
  -H "Content-Type: application/json" \
  -d '{"judge_odds": "+180", "roman_odds": "+2000"}'
```

---

## Testing Notifications

Send yourself a test report without waiting until Monday:

**From the dashboard:** Hit the "Send Weekly Report Now" button.

**From the command line:**
```bash
curl -X POST http://localhost:8000/api/trigger-report
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard |
| GET | `/api/comparison` | Full head-to-head data |
| GET | `/api/schedule/roman` | Red Sox schedule |
| GET | `/api/schedule/judge` | Yankees schedule |
| GET | `/api/odds` | Current MVP odds |
| GET | `/api/trends/roman` | Roman's season trend data |
| GET | `/api/trends/judge` | Judge's season trend data |
| GET | `/api/gamelog/roman` | Roman's game log |
| GET | `/api/gamelog/judge` | Judge's game log |
| POST | `/api/odds/manual` | Update odds manually |
| POST | `/api/trigger-report` | Send weekly report now |
| POST | `/api/cache/clear` | Force fresh data |
| GET | `/api/cache-stats` | Debug: see cache state |
| GET | `/health` | Health check |
| GET | `/docs` | FastAPI auto-docs |

---

## How the Bet Score Works

The score is a weighted formula designed to mirror how MVP voters actually think. Scores always sum to 100 (if Judge is at 62, Roman is at 38).

| Stat | Weight | Why |
|------|--------|-----|
| fWAR | 25% | Best single-number value measure. Captures offense, defense, baserunning. MVP voters use this even when they say "eye test." |
| wRC+ | 20% | Park and league-adjusted offensive production. 100 = league average. Higher is better. |
| HR | 18% | Voters love dingers. Judge's 62-HR season proves it. Unfair? Yes. Real? Also yes. |
| OPS | 15% | Classic power + patience. Easy to understand, hard to fake. |
| RBI | 10% | Context-dependent but voters care. Not gonna pretend they don't. |
| Runs + SB | 12% | Rounds out the offensive picture. Roman has speed here. |

Each stat is compared between the two players and weighted by the above. The formula adjusts automatically if FanGraphs data is unavailable (falls back to a basic version with just MLB Stats API data).

---

## Known Limitations

### Roman Anthony's MLB debut
Roman Anthony is a 2025 prospect. If he's in the minors, the MLB Stats API returns no stats and the dashboard shows zeros. The app handles this gracefully — you'll see "N/A" for his stats until he's called up. His stats will auto-populate as soon as he's on the active roster.

### WAR and wRC+ availability
FanGraphs doesn't have an official API. Their leaderboard endpoint has been stable for years but could change. If it breaks, the bet score formula automatically falls back to a basic version (HR, OPS, RBI, Runs, SB only). The "weights_used" field in the API response tells you which mode is active.

### MVP odds markets
AL MVP futures don't trade year-round. Early in the season (April/May) the market might not be open. The odds API will return nothing and fall back to your manual entries. **This is expected** — just update manually when the market opens.

### Free hosting and the scheduler
Render's free tier sleeps when inactive. The APScheduler runs inside the app process, so if the app is asleep at 8 AM Monday, the report won't fire. Two fixes:
1. Set up `cron-job.org` to ping your `/health` endpoint every 10 minutes (free)
2. Upgrade to Render's paid tier ($7/month) or Railway ($5/month)

### Rate limits
- **MLB Stats API**: No documented rate limit but be reasonable. The 15-min cache means you're making ~4 requests/hour per endpoint. You're fine.
- **FanGraphs**: Same story — no official limits but cache keeps it low.
- **The Odds API**: 500 requests/month free. With 6-hour caching you're using ~120/month.

---

## Customizing

**Add more stats to the comparison table:**
Edit `STAT_ROWS` in `static/app.js` — add any key that the `/api/comparison` response includes.

**Change the bet score formula:**
Edit `WEIGHTS` in `scoring.py`. The weights must sum to `1.0`.

**Change notification timing:**
Update `WEEKLY_REPORT_DAY`, `WEEKLY_REPORT_HOUR`, `WEEKLY_REPORT_MINUTE` in `.env`.

**Add a third player to the bet** (e.g., Gunnar Henderson):
This requires a bit of work — the architecture supports two players right now. You'd need to add config vars, extend the API layer, and update the dashboard layout. Not hard but not a one-liner.

**Change the trash talk lines:**
Edit the `TRASH_TALK` dict in `notifications.py`. Go off.

---

## Project Structure

```
roman-vs-judge/
├── main.py              # FastAPI app + all routes
├── mlb_api.py           # MLB Stats API wrapper (season stats, schedules, game logs)
├── fangraphs_api.py     # FanGraphs unofficial API (WAR, wRC+)
├── odds.py              # MVP odds (The Odds API + manual fallback)
├── notifications.py     # Email (Gmail SMTP) + SMS (Twilio) sending
├── scheduler.py         # APScheduler weekly report job
├── scoring.py           # Bet score formula
├── cache.py             # In-memory TTL cache decorator
├── config.py            # All settings loaded from .env
├── static/
│   ├── index.html       # Single-page dashboard
│   ├── style.css        # Dark baseball theme
│   └── app.js           # All frontend JS — fetch, render, charts
├── templates/
│   └── weekly_email.html # Jinja2 HTML email template
├── requirements.txt
├── .env.example         # Template — copy to .env and fill in
├── .gitignore
├── Procfile             # For Render/Railway deployment
└── render.yaml          # Render.com service config
```

---

Made with way too much attention to detail for a brother-vs-brother bet. 🤝⚾
