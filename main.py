import os
import random
import yaml
import asyncio
from datetime import time
from zoneinfo import ZoneInfo
from aiohttp import web
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# ===== ENV =====
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Tallinn"))
ADMIN_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

# ===== MESSAGES =====
with open("messages.yaml", "r", encoding="utf-8") as f:
    MSG = yaml.safe_load(f) or {}

AFFS = MSG.get("affirmations", ["Stay sharp."])
MOTS = MSG.get("motivations", ["Move."])
WEEKLY = MSG.get("weekly", "Weekly recap time.")

# ===== COMMANDS =====
async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is alive.\n\nCommands:\n/affirmation\n/motivate\n/help")

async def cmd_help(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/affirmation – send one now\n"
        "/motivate – send one now\n"
        "/help – this message"
    )

async def cmd_affirmation(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(AFFS))

async def cmd_motivate(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(MOTS))

# ===== SCHEDULED JOBS =====
async def send_affirmation(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(ADMIN_ID, random.choice(AFFS))

async def send_motivation(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(ADMIN_ID, random.choice(MOTS))

async def send_weekly_recap(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(ADMIN_ID, WEEKLY)

# ===== TELEGRAM BOT LOOP =====
async def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()

    # command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("affirmation", cmd_affirmation))
    app.add_handler(CommandHandler("motivate", cmd_motivate))

# === Temporary command to get chat ID ===
async def cmd_getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Chat ID: {chat_id}")

app.add_handler(CommandHandler("getid", cmd_getid))

    # schedules
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
