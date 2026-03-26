"""
notifications.py — Weekly report via Email (SMTP) and SMS (Twilio)

The weekly report runs every Monday at 8 AM ET and covers:
  - Each player's stats for the prior week
  - Season totals to date
  - Who "won" the week + overall season lead
  - Current MVP odds
  - Auto-generated trash talk based on who's leading

Email: Clean HTML template with team colors
SMS: Concise plain-text version
"""
import smtplib
import logging
import random
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date, timedelta
from typing import Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape

import config

logger = logging.getLogger(__name__)

# Jinja2 for the HTML email template
_jinja = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)

# ─── Trash Talk Lines ─────────────────────────────────────────────────────────
# Indexed by who's leading: "judge" or "roman"
TRASH_TALK = {
    "judge": [
        "Judge is out here playing a different game entirely. Roman who? 👀",
        "Aaron Judge said 'I'll take that bet' and he meant it. 📈",
        "At this rate, Roman's gonna owe Judge a lot more than bragging rights. 👑",
        "The Bronx is burning and Roman Anthony is the kindling. 🔥",
        "Judge is putting on a clinic. Someone check on your brother. 😬",
        "Roman Anthony called — he wanted me to say congrats to Judge. Allegedly. 🤷",
        "If the AL MVP award was a courtroom, Judge would already have a verdict. ⚖️",
    ],
    "roman": [
        "Roman Anthony is making this bet look easy. The kid is that good. 🔥",
        "The Red Sox rookie said hold my juice box and is going OFF. 🚀",
        "Roman Anthony: too young, too good, too bad for your bracket. 😤",
        "Your boy Aaron Judge is catching strays from a 22-year-old. Ouch. 💀",
        "Roman Anthony just called — he says thanks for the easy money. 📞",
        "The future arrived early, and it's wearing a Red Sox cap. 🧢",
        "Fenway Park is loud right now and Judge fans are quiet. Very quiet. 🤫",
    ],
    "tied": [
        "It's a dead heat. Both guys showing out. MVP voters are sweating. 🤝",
        "Too close to call right now. Check back next week — things could get spicy. 🌶️",
        "A bet this close means neither of you actually knows baseball. Respectfully. 😂",
    ]
}


def generate_passan_summary(report_data: dict) -> Optional[str]:
    """
    Generate a Jeff Passan-style narrative summary of the week using Claude.
    Returns 2-3 paragraphs of prose, or None if the API key isn't configured
    or the call fails.
    """
    if not config.ANTHROPIC_API_KEY:
        logger.debug("ANTHROPIC_API_KEY not set — skipping Passan summary")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

        rw = report_data.get("roman_week") or {}
        jw = report_data.get("judge_week") or {}
        rs = (report_data.get("roman") or {}).get("season_stats") or {}
        js = (report_data.get("judge") or {}).get("season_stats") or {}
        odds = report_data.get("odds") or {}
        week_of = report_data.get("week_of", "this week")
        week_winner = report_data.get("week_winner", "tied")
        season_leader = report_data.get("season_leader", "tied")

        def _stat(d, key, default="N/A"):
            v = d.get(key)
            return str(v) if v is not None else default

        stats_block = f"""
WEEK OF: {week_of}

ROMAN ANTHONY (BOS) — This Week:
  AVG {_stat(rw,'avg','.---')} | OBP {_stat(rw,'obp','.---')} | SLG {_stat(rw,'slg','.---')} | OPS {_stat(rw,'ops','.---')}
  HR {_stat(rw,'hr','0')} | RBI {_stat(rw,'rbi','0')} | R {_stat(rw,'runs','0')} | SB {_stat(rw,'sb','0')} | K {_stat(rw,'k','0')} | Games {_stat(rw,'games','0')}

AARON JUDGE (NYY) — This Week:
  AVG {_stat(jw,'avg','.---')} | OBP {_stat(jw,'obp','.---')} | SLG {_stat(jw,'slg','.---')} | OPS {_stat(jw,'ops','.---')}
  HR {_stat(jw,'hr','0')} | RBI {_stat(jw,'rbi','0')} | R {_stat(jw,'runs','0')} | SB {_stat(jw,'sb','0')} | K {_stat(jw,'k','0')} | Games {_stat(jw,'games','0')}

SEASON TOTALS:
  Roman — AVG {_stat(rs,'avg','.---')} | HR {_stat(rs,'hr','0')} | RBI {_stat(rs,'rbi','0')} | OPS {_stat(rs,'ops','.---')} | fWAR {_stat(rs,'fwar','N/A')} | wRC+ {_stat(rs,'wrc_plus','N/A')}
  Judge — AVG {_stat(js,'avg','.---')} | HR {_stat(js,'hr','0')} | RBI {_stat(js,'rbi','0')} | OPS {_stat(js,'ops','.---')} | fWAR {_stat(js,'fwar','N/A')} | wRC+ {_stat(js,'wrc_plus','N/A')}

AL MVP ODDS (FanDuel):
  Judge: {(odds.get('judge') or {}).get('odds','N/A')} ({(odds.get('judge') or {}).get('implied_prob','?')}% implied)
  Roman: {(odds.get('roman') or {}).get('odds','N/A')} ({(odds.get('roman') or {}).get('implied_prob','?')}% implied)

WEEK WINNER: {week_winner.upper()}
SEASON LEADER: {season_leader.upper()}

CONTEXT: This is a season-long bet between two friends — one rooting for Roman Anthony (Red Sox rookie OF) to win AL MVP, the other backing Aaron Judge (Yankees RF, reigning AL MVP). The bet started before the 2025 season.
""".strip()

        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=600,
            system=(
                "You are Jeff Passan, ESPN's lead baseball writer. "
                "Write in his signature style: cinematic, dramatic, historically aware, "
                "deeply reverent of the game. Use vivid prose. Give weight to statistics — "
                "don't just recite them, make the reader feel what they mean. "
                "You may reference baseball history, the pressures of the sport, what's at stake. "
                "Keep it punchy. Two short paragraphs max. No bullet points. No headers. "
                "Plain text only — no markdown, no asterisks, no HTML."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Write a two-paragraph recap of this week's Roman Anthony vs. Aaron Judge matchup "
                    f"for a weekly bet tracker email. Make it feel like a real Passan column — "
                    f"not a summary, a story. Here are the numbers:\n\n{stats_block}"
                )
            }]
        )

        text = next(
            (b.text for b in response.content if b.type == "text"), None
        )
        if text:
            logger.info("Passan summary generated successfully")
        return text

    except Exception as e:
        logger.warning(f"Passan summary generation failed: {e}")
        return None


def generate_trash_talk(winner: str) -> str:
    """Pick a random trash-talk line for the weekly winner."""
    lines = TRASH_TALK.get(winner, TRASH_TALK["tied"])
    return random.choice(lines)


# ─── Email ────────────────────────────────────────────────────────────────────

def send_weekly_email(report_data: dict) -> bool:
    """
    Send the HTML weekly report email to both recipients.
    Uses Gmail SMTP with an App Password.
    Returns True if both sends succeed, False if either fails.
    """
    if not all([config.SMTP_USER, config.SMTP_PASSWORD]):
        logger.warning("Email not configured (missing SMTP_USER or SMTP_PASSWORD)")
        return False

    recipients = []
    if config.YOUR_EMAIL:
        recipients.append((config.YOUR_NAME, config.YOUR_EMAIL))
    if config.BROTHER_EMAIL:
        recipients.append((config.BROTHER_NAME, config.BROTHER_EMAIL))

    if not recipients:
        logger.warning("No email recipients configured")
        return False

    html_body = _render_email_html(report_data)
    text_body = _render_email_text(report_data)

    week_of = report_data.get("week_of", date.today().strftime("%B %d"))
    subject = f"🏆 Roman vs Judge — Week of {week_of}"

    success = True
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)

            for name, email in recipients:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = f"{config.EMAIL_FROM_NAME} <{config.SMTP_USER}>"
                msg["To"] = email

                msg.attach(MIMEText(text_body, "plain"))
                msg.attach(MIMEText(html_body, "html"))

                server.sendmail(config.SMTP_USER, email, msg.as_string())
                logger.info(f"Weekly email sent to {name} <{email}>")

    except smtplib.SMTPException as e:
        logger.error(f"Email send failed: {e}")
        success = False

    return success


# ─── SMS ──────────────────────────────────────────────────────────────────────

def send_weekly_sms(report_data: dict) -> bool:
    """
    Send concise weekly summary SMS via Twilio.
    Twilio free trial: ~$15 credit, ~$0.008/SMS after that.
    """
    if not all([config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN, config.TWILIO_FROM_NUMBER]):
        logger.warning("SMS not configured (missing Twilio credentials)")
        return False

    recipients = []
    if config.YOUR_PHONE:
        recipients.append((config.YOUR_NAME, config.YOUR_PHONE))
    if config.BROTHER_PHONE:
        recipients.append((config.BROTHER_NAME, config.BROTHER_PHONE))

    if not recipients:
        logger.warning("No SMS recipients configured")
        return False

    # Import Twilio here so the app still runs if twilio isn't installed
    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioException
    except ImportError:
        logger.error("Twilio not installed. Run: pip install twilio")
        return False

    message_body = _render_sms(report_data)
    client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)

    success = True
    for name, phone in recipients:
        try:
            msg = client.messages.create(
                body=message_body,
                from_=config.TWILIO_FROM_NUMBER,
                to=phone,
            )
            logger.info(f"SMS sent to {name} ({phone}): SID {msg.sid}")
        except Exception as e:
            logger.error(f"SMS to {name} ({phone}) failed: {e}")
            success = False

    return success


# ─── Report Renderers ─────────────────────────────────────────────────────────

def _render_email_html(data: dict) -> str:
    """Render the Jinja2 HTML email template."""
    try:
        template = _jinja.get_template("weekly_email.html")
        return template.render(**data)
    except Exception as e:
        logger.error(f"Email template render failed: {e}")
        # Fallback to plain-text wrapped in minimal HTML
        return f"<pre>{_render_email_text(data)}</pre>"


def _render_email_text(data: dict) -> str:
    """Plain-text version of the weekly report (also used as SMS fallback)."""
    roman = data.get("roman", {})
    judge = data.get("judge", {})
    roman_week = data.get("roman_week", {})
    judge_week = data.get("judge_week", {})
    odds = data.get("odds", {})
    week_of = data.get("week_of", "")
    winner = data.get("week_winner", "tied")
    season_leader = data.get("season_leader", "tied")
    trash_talk = data.get("trash_talk", "")
    score = data.get("score", {})

    lines = [
        f"🏆 ROMAN vs JUDGE — Week of {week_of}",
        "=" * 40,
        "",
        "📅 THIS WEEK'S STATS:",
        f"Roman: {_fmt_week(roman_week)}",
        f"Judge: {_fmt_week(judge_week)}",
        "",
        f"WEEK WINNER: {'🔴 Roman Anthony' if winner == 'roman' else '⚫ Aaron Judge' if winner == 'judge' else '🤝 Tied'}",
        "",
        "📊 SEASON TOTALS:",
        f"Roman: {_fmt_season(roman.get('season_stats', {}))}",
        f"  WAR: {_fmt_val(roman.get('fwar'))} | wRC+: {_fmt_val(roman.get('wrc_plus'))}",
        f"Judge: {_fmt_season(judge.get('season_stats', {}))}",
        f"  WAR: {_fmt_val(judge.get('fwar'))} | wRC+: {_fmt_val(judge.get('wrc_plus'))}",
        "",
        f"🏅 OVERALL LEAD: {'🔴 Roman Anthony' if season_leader == 'roman' else '⚫ Aaron Judge' if season_leader == 'judge' else '🤝 Tied'}",
        f"  Bet Score: Roman {score.get('roman', 0)} — Judge {score.get('judge', 0)}",
        "",
        "💰 MVP ODDS:",
        f"  Aaron Judge: {odds.get('judge', {}).get('odds', 'N/A')}",
        f"  Roman Anthony: {odds.get('roman', {}).get('odds', 'N/A')}",
        "",
        f"💬 {trash_talk}",
        "",
        "— Your Bet Tracker 🤖",
    ]
    return "\n".join(lines)


def _render_sms(data: dict) -> str:
    """Ultra-concise SMS version. Twilio has a 1600 char limit per segment."""
    roman_week = data.get("roman_week", {})
    judge_week = data.get("judge_week", {})
    odds = data.get("odds", {})
    winner = data.get("week_winner", "tied")
    score = data.get("score", {})
    trash_talk = data.get("trash_talk", "")
    week_of = data.get("week_of", "")

    winner_str = "Roman" if winner == "roman" else "Judge" if winner == "judge" else "Tie"

    # Keep it short — aim for under 800 chars so it's a single SMS
    parts = [
        f"R vs J | Wk of {week_of}",
        f"Roman this wk: {roman_week.get('avg','.---')} {roman_week.get('hr',0)}HR {roman_week.get('rbi',0)}RBI {roman_week.get('ops','.---')}OPS",
        f"Judge this wk: {judge_week.get('avg','.---')} {judge_week.get('hr',0)}HR {judge_week.get('rbi',0)}RBI {judge_week.get('ops','.---')}OPS",
        f"Wk winner: {winner_str}",
        f"Season: Roman {score.get('roman',0)} - Judge {score.get('judge',0)}",
        f"MVP: Judge {odds.get('judge',{}).get('odds','?')} | Roman {odds.get('roman',{}).get('odds','?')}",
        trash_talk,
    ]
    return "\n".join(parts)


# ─── Formatting Helpers ───────────────────────────────────────────────────────

def _fmt_week(stats: dict) -> str:
    if not stats:
        return "No games this week"
    return (f".{stats.get('avg','---').lstrip('.')} AVG | "
            f"{stats.get('hr',0)} HR | "
            f"{stats.get('rbi',0)} RBI | "
            f"{stats.get('ops','---')} OPS | "
            f"{stats.get('games',0)} G")


def _fmt_season(stats: dict) -> str:
    if not stats:
        return "N/A"
    return (f"{stats.get('avg','.---')} AVG | "
            f"{stats.get('obp','.---')} OBP | "
            f"{stats.get('slg','.---')} SLG | "
            f"{stats.get('hr',0)} HR | "
            f"{stats.get('rbi',0)} RBI | "
            f"{stats.get('games',0)} G")


def _fmt_val(val) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:.1f}"
    return str(val)
