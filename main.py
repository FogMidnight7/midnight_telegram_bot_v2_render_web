import os
import random
import yaml
import asyncio
from datetime import time
from zoneinfo import ZoneInfo
from aiohttp import web

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ===== ENV =====
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Tallinn"))

# Admin DM fallback (optional), but primary target is Tier-3 channel:
ADMIN_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
TARGET_ID = int(os.environ.get("FOGWALKERS_TIER3_ID", str(ADMIN_ID)))  # <- Tier-3 channel (-100...)

# ===== MESSAGES =====
with open("messages.yaml", "r", encoding="utf-8") as f:
    MSG = yaml.safe_load(f) or {}

AFFS = MSG.get("affirmations", ["Stay sharp."])
MOTS = MSG.get("motivations", ["Move."])
WEEKLY = MSG.get("weekly", "Weekly recap time.")

# ===== COMMANDS =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot is alive.\n\nCommands:\n"
        "/affirmation – send one now\n"
        "/motivate – send one now\n"
        "/broadcast – DM-only test to Tier-3\n"
        "/help – this message"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/affirmation – send one now\n"
        "/motivate – send one now\n"
        "/broadcast – DM-only test to Tier-3\n"
        "/help – this message"
    )

async def cmd_affirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(AFFS))

async def cmd_motivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(MOTS))

# Temporary: get the chat ID of where the command was sent
async def cmd_getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text=f"Chat ID: {chat_id}")

# DM -> posts into Tier-3 channel (TARGET_ID), confirms in DM
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=TARGET_ID, text="🕯️ Test broadcast from Midnight.")
    if update.message:
        await update.message.reply_text("✅ Sent to Tier-3 channel.")

# ===== SCHEDULED JOBS =====
async def send_affirmation(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(TARGET_ID, random.choice(AFFS))

async def send_motivation(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(TARGET_ID, random.choice(MOTS))

async def send_weekly_recap(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(TARGET_ID, WEEKLY)

# ===== TELEGRAM BOT LOOP =====
async def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()

    # command handlers (all registered inside run_bot so 'app' is in scope)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("affirmation", cmd_affirmation))
    app.add_handler(CommandHandler("motivate", cmd_motivate))
    app.add_handler(CommandHandler("getid", cmd_getid))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # schedules (requires python-telegram-bot[job-queue])
    jq = app.job_queue
    jq.run_daily(send_affirmation, time=time(6, 0, tzinfo=TZ), name="daily_aff")
    jq.run_daily(send_motivation, time=time(13, 0, tzinfo=TZ), name="daily_motivate")
    jq.run_daily(send_weekly_recap, time=time(20, 0, tzinfo=TZ), days=(6,), name="weekly_recap")

    # start polling + stay alive
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

# ===== HEALTHCHECK WEB SERVER (for Render Web Service) =====
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

# ===== MAIN =====
async def main():
    await asyncio.gather(run_bot(), run_web())

if __name__ == "__main__":
    asyncio.run(main())
