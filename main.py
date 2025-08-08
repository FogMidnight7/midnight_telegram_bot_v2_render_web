import os
import random
import yaml
import asyncio
from datetime import time
from zoneinfo import ZoneInfo
from aiohttp import web
from telegram.ext import ApplicationBuilder, CommandHandler

# --- ENV VARS ---
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Tallinn"))
ADMIN_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

# --- LOAD MESSAGES ---
with open("messages.yaml", "r", encoding="utf-8") as f:
    MSG = yaml.safe_load(f)

# --- COMMAND HANDLERS ---
async def start(update, context):
    await update.message.reply_text("Bot is alive.")

# --- SCHEDULED TASKS ---
async def send_affirmation(context):
    await context.bot.send_message(ADMIN_ID, random.choice(MSG.get("affirmations", ["Stay sharp."])))

async def send_motivation(context):
    await context.bot.send_message(ADMIN_ID, random.choice(MSG.get("motivations", ["Move."])))

async def send_weekly_recap(context):
    await context.bot.send_message(ADMIN_ID, MSG.get("weekly", "Weekly recap time."))

# --- TELEGRAM BOT LOOP ---
async def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    jq = app.job_queue
    jq.run_daily(send_affirmation, time=time(6, 0, tzinfo=TZ), name="daily_aff")
    jq.run_daily(send_motivation, time=time(13, 0, tzinfo=TZ), name="daily_motivate")
    jq.run_daily(send_weekly_recap, time=time(20, 0, tzinfo=TZ), days=(6,), name="weekly_recap")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()  # Keeps the bot alive

# --- HEALTHCHECK WEB SERVER ---
async def run_web():
    async def health(_):
        return web.json_response({"status": "ok"})
    app = web.Application()
    app.router.add_get("/health", health)
    port = int(os.environ.get("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- MAIN ---
async def main():
    await asyncio.gather(run_bot(), run_web())

if __name__ == "__main__":
    asyncio.run(main())
