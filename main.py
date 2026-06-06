import os
import random
import yaml
import asyncio
import logging
from datetime import time, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from aiohttp import web, ClientSession

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
log = logging.getLogger("midnight")

# ---------- ENV ----------
def must_get(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Required env var {key} is missing")
    return val

TOKEN = must_get("TELEGRAM_BOT_TOKEN")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Tallinn"))
ADMIN_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
YOUTUBE_SEEN_FILE = os.environ.get("YOUTUBE_SEEN_FILE", "youtube_seen_links.txt")

if os.environ.get("FOGWALKERS_TIER3_ID"):
    TARGET_ID = int(os.environ["FOGWALKERS_TIER3_ID"])
else:
    TARGET_ID = ADMIN_ID
    log.warning("[BOT] FOGWALKERS_TIER3_ID not set; falling back to ADMIN_CHAT_ID=%s", ADMIN_ID)

log.info("[BOT] Boot with TARGET_ID=%s TZ=%s", TARGET_ID, TZ)

# ---------- MESSAGES ----------
try:
    with open("messages.yaml", "r", encoding="utf-8") as f:
        MSG = yaml.safe_load(f) or {}
except FileNotFoundError:
    log.warning("[BOT] messages.yaml not found; using defaults")
    MSG = {}

AFFS = MSG.get("affirmations", ["Stay sharp."])
MOTS = MSG.get("motivations", ["Move."])
WEEKLY = MSG.get("weekly", "Weekly recap time.")

# ---------- YOUTUBE SCOUT ----------
YT_SEARCH_QUERIES = [
    "burnout overwhelm",
    "burnout exhausted",
    "overthinking stuck",
    "overthinking decision",
    "procrastination avoidance",
    "procrastination guilt",
    "self sabotage habits",
    "consistency motivation",
    "discipline burnout",
    "stuck in life habits",
    "tired of starting over",
    "why do I keep procrastinating",
    "I keep restarting",
    "I feel stuck but know what to do",
]

HIGH_SIGNAL_TERMS = {
    "stuck": 1.1,
    "overwhelmed": 1.2,
    "overwhelm": 1.2,
    "burnout": 1.2,
    "burned out": 1.2,
    "exhausted": 1.2,
    "tired": 0.8,
    "procrastinate": 1.3,
    "procrastination": 1.3,
    "avoid": 1.2,
    "avoiding": 1.2,
    "avoidance": 1.2,
    "restart": 1.2,
    "restarting": 1.2,
    "starting over": 1.3,
    "same pattern": 1.4,
    "loop": 1.1,
    "discipline": 0.8,
    "motivation": 0.8,
    "consistent": 0.9,
    "consistency": 0.9,
    "self sabotage": 1.4,
    "habit": 0.7,
    "habits": 0.7,
    "trust myself": 1.5,
    "promise": 1.0,
    "promises": 1.0,
    "this is me": 1.5,
    "needed this": 1.2,
    "hit hard": 1.2,
    "called out": 1.2,
    "feel attacked": 1.2,
    "i don't know why": 1.5,
    "i dont know why": 1.5,
    "can't focus": 1.2,
    "cant focus": 1.2,
    "anxiety": 0.8,
    "mental": 0.6,
    "comfort": 1.0,
    "identity": 1.0,
}

LOW_SIGNAL_TERMS = [
    "great video",
    "nice video",
    "thanks for sharing",
    "thank you for sharing",
    "first",
    "lol",
    "haha",
    "bro",
    "subscribe",
    "check my channel",
    "crypto",
    "trump",
    "biden",
    "religion",
    "god bless",
]

async def youtube_api_get(session: ClientSession, endpoint: str, params: dict) -> dict:
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}"
    params = dict(params)
    params["key"] = YOUTUBE_API_KEY
    async with session.get(url, params=params, timeout=20) as resp:
        data = await resp.json(content_type=None)
        if resp.status >= 400:
            raise RuntimeError(data.get("error", {}).get("message", f"YouTube API error {resp.status}"))
        return data

async def search_youtube_videos(session: ClientSession, query: str, max_results: int = 5) -> list[dict]:
    published_after = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    data = await youtube_api_get(session, "search", {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "order": "relevance",
        "safeSearch": "moderate",
        "relevanceLanguage": "en",
        "publishedAfter": published_after,
    })
    videos = []
    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        if video_id:
            videos.append({
                "video_id": video_id,
                "title": item.get("snippet", {}).get("title", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            })
    return videos

async def fetch_newest_comments(session: ClientSession, video_id: str, max_results: int = 20) -> list[str]:
    try:
        data = await youtube_api_get(session, "commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": max_results,
            "order": "time",
            "textFormat": "plainText",
        })
    except Exception as e:
        log.info("[YT] comments unavailable for %s: %s", video_id, e)
        return []

    comments = []
    for item in data.get("items", []):
        text = (
            item.get("snippet", {})
            .get("topLevelComment", {})
            .get("snippet", {})
            .get("textDisplay", "")
        )
        if text:
            comments.append(text.strip())
    return comments

def score_comment(comment: str) -> float:
    text = comment.lower().strip()
    if not text or len(text) < 25:
        return 0.0
    if any(term in text for term in LOW_SIGNAL_TERMS):
        return 0.0

    score = 2.0

    # Personal language usually means a real reply opportunity, not generic praise.
    personal_markers = [" i ", " i've ", " im ", " i'm ", " me ", " my ", " myself ", "i’m", "i've", "i "]
    if any(marker in f" {text} " for marker in personal_markers):
        score += 1.3

    for term, weight in HIGH_SIGNAL_TERMS.items():
        if term in text:
            score += weight

    # Emotional/context detail is useful; ultra-short reactions are not.
    words = text.split()
    if 12 <= len(words) <= 120:
        score += 1.0
    elif len(words) > 120:
        score += 0.3

    # Open uncertainty is usually a strong Midnight entry point.
    if "?" in text or "why" in text or "how" in text:
        score += 0.6

    # Cap and round.
    return round(min(score, 10.0), 1)

def read_seen_youtube_links() -> set[str]:
    try:
        with open(YOUTUBE_SEEN_FILE, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set()

def write_seen_youtube_links(urls: list[str]) -> None:
    if not urls:
        return
    with open(YOUTUBE_SEEN_FILE, "a", encoding="utf-8") as f:
        for url in urls:
            f.write(url + "\n")

async def run_youtube_scout() -> list[dict]:
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY is missing in Render environment variables.")

    seen = read_seen_youtube_links()
    candidates = {}
    queries = random.sample(YT_SEARCH_QUERIES, k=min(6, len(YT_SEARCH_QUERIES)))

    async with ClientSession() as session:
        for query in queries:
            try:
                videos = await search_youtube_videos(session, query, max_results=5)
            except Exception as e:
                log.exception("[YT] search failed for query=%s: %s", query, e)
                continue

            for video in videos:
                url = video["url"]
                if url in seen or url in candidates:
                    continue

                comments = await fetch_newest_comments(session, video["video_id"], max_results=20)
                if not comments:
                    continue

                best_score = 0.0
                for comment in comments:
                    best_score = max(best_score, score_comment(comment))

                if best_score >= 8.0:
                    candidates[url] = {
                        "score": best_score,
                        "url": url,
                    }

    results = sorted(candidates.values(), key=lambda item: item["score"], reverse=True)[:5]
    write_seen_youtube_links([item["url"] for item in results])
    return results

async def cmd_ytscout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("🔎 YouTube Scout hunting…")

    try:
        results = await run_youtube_scout()
        if not results:
            msg = "YOUTUBE SCOUT\n\nNo 8.0+ matches found this run. Try again later."
        else:
            lines = ["YOUTUBE SCOUT"]
            for idx, item in enumerate(results, start=1):
                lines.append(f"\n{idx}.\nMatch Score: {item['score']}\nLink: {item['url']}")
            msg = "\n".join(lines)

        if update.message:
            await update.message.reply_text(msg, disable_web_page_preview=True)
    except Exception as e:
        log.exception("[YT] /ytscout failed")
        if update.message:
            await update.message.reply_text(f"❌ YouTube Scout failed: {e}")

# ---------- COMMANDS ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot is alive.\n\nCommands:\n"
        "/affirmation – send one now\n"
        "/motivate – send one now\n"
        "/broadcast <text> – post to Tier-3\n"
        "/ytscout – find 5 YouTube comment opportunities\n"
        "/help – this message"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/affirmation – send one now\n"
        "/motivate – send one now\n"
        "/broadcast <text> – post to Tier-3 (or reply to a message and send /broadcast)\n"
        "/ytscout – find 5 YouTube comment opportunities\n"
        "/help – this message"
    )

async def cmd_affirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(AFFS))

async def cmd_motivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(MOTS))

# /broadcast accepts free text after the command OR forwards the replied message text/caption
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage:
      /broadcast Your message here
    Or:
      reply to any message with /broadcast (it will forward the replied text/caption)
    """
    try:
        text = " ".join(context.args).strip() if context.args else ""

        if not text and update.message and update.message.reply_to_message:
            replied = update.message.reply_to_message
            if replied.text and replied.text.strip():
                text = replied.text.strip()
            elif replied.caption and replied.caption.strip():
                text = replied.caption.strip()

        if not text:
            text = "🕯️ Test broadcast from Midnight."

        log.info("[BOT] /broadcast by %s in chat %s → '%s'",
                 update.effective_user.id if update.effective_user else "?",
                 update.effective_chat.id if update.effective_chat else "?",
                 text)

        await context.bot.send_message(chat_id=TARGET_ID, text=text)

        if update.message:
            await update.message.reply_text("✅ Sent to Tier-3 channel.")
    except Exception as e:
        log.exception("[BOT] Broadcast failed")
        if update.message:
            await update.message.reply_text(f"❌ Broadcast failed: {e}")

# ---------- SCHEDULED JOBS ----------
async def send_affirmation(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(TARGET_ID, random.choice(AFFS))
    except Exception:
        log.exception("[JOB] send_affirmation failed")

async def send_motivation(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(TARGET_ID, random.choice(MOTS))
    except Exception:
        log.exception("[JOB] send_motivation failed")

async def send_weekly_recap(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(TARGET_ID, WEEKLY)
    except Exception:
        log.exception("[JOB] send_weekly_recap failed")

# ---------- TELEGRAM BOT LOOP ----------
async def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()

    # handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("affirmation", cmd_affirmation))
    app.add_handler(CommandHandler("motivate", cmd_motivate))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("ytscout", cmd_ytscout))

    # schedules (requires python-telegram-bot[job-queue] in requirements.txt)
    jq = app.job_queue
    jq.run_daily(send_affirmation, time=time(6, 0, tzinfo=TZ), name="daily_aff")
    jq.run_daily(send_motivation, time=time(13, 0, tzinfo=TZ), name="daily_motivate")
    jq.run_daily(send_weekly_recap, time=time(20, 0, tzinfo=TZ), days=(6,), name="weekly_recap")

    # start polling + stay alive
    log.info("[BOT] Initializing…")
    await app.initialize()
    log.info("[BOT] Starting…")
    await app.start()
    log.info("[BOT] Starting polling…")
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("[BOT] Polling active. Waiting forever.")
    await asyncio.Event().wait()

# ---------- HEALTHCHECK WEB SERVER (Render) ----------
async def run_web():
    async def health(_):
        return web.json_response({"status": "ok"})
    webapp = web.Application()
    webapp.router.add_get("/health", health)
    port = int(os.environ.get("PORT", "10000"))
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("[WEB] Health endpoint running on /health port=%s", port)

# ---------- MAIN ----------
async def main():
    await asyncio.gather(run_bot(), run_web())

if __name__ == "__main__":
    asyncio.run(main())
