import os
import random
import yaml
import asyncio
import logging
from datetime import time
from zoneinfo import ZoneInfo
from aiohttp import web

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

# ---------- COMMANDS ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot is alive.\n\nCommands:\n"
        "/affirmation – send one now\n"
        "/motivate – send one now\n"
        "/broadcast <text> – post to Tier-3\n"
        "/help – this message"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/affirmation – send one now\n"
        "/motivate – send one now\n"
        "/broadcast <text> – post to Tier-3 (or reply to a message and send /broadcast)\n"
        "/help – this message"
    )

async def cmd_affirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(AFFS))

async def cmd_motivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(MOTS))

async def cmd_getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text=f"Chat ID: {chat_id}")

# /broadcast accepts free text after the command OR forwards the replied message text/caption
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage:
      /broadcast Your message here
    Or:
      reply to any message with /broadcast (it will forward the replied text/caption)
    """
    try:
        # Prefer args after the command
        text = " ".join(context.args).strip() if context.args else ""

        # If no args, but user replied to a message, pick reply text/caption
        if not text and update.message and update.message.reply_to_message:
            replied = update.message.reply_to_message
            if replied.text and replied.text.strip():
                text = replied.text.strip()
            elif replied.caption and replied.caption.strip():
                text = replied.caption.strip()

        # Final fallback
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
    app.add_handler(CommandHandler("getid", cmd_getid))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

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
