import os, random
from datetime import time
from zoneinfo import ZoneInfo
from telegram.ext import ApplicationBuilder, CommandHandler
import yaml

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Tallinn"))
ADMIN_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

# --- load messages
with open("messages.yaml", "r", encoding="utf-8") as f:
    MSG = yaml.safe_load(f)

async def start(update, context):
    await update.message.reply_text("Bot is alive.")

async def send_affirmation(context):
    text = random.choice(MSG.get("affirmations", ["Stay sharp."]))
    await context.bot.send_message(ADMIN_ID or context.job.chat_id, text)

async def send_motivation(context):
    text = random.choice(MSG.get("motivations", ["Move."]))
    await context.bot.send_message(ADMIN_ID or context.job.chat_id, text)

async def send_weekly_recap(context):
    text = MSG.get("weekly_recap", "Weekly recap time.")
    await context.bot.send_message(ADMIN_ID or context.job.chat_id, text)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    jq = app.job_queue
    # Daily 06:00 — affirmations
    jq.run_daily(send_affirmation, time=time(6, 0, tzinfo=TZ), name="daily_aff")
    # Daily 13:00 — motivation
    jq.run_daily(send_motivation, time=time(13, 0, tzinfo=TZ), name="daily_motivate")
    # Sundays 20:00 — weekly recap (0=Mon … 6=Sun)
    jq.run_daily(send_weekly_recap, time=time(20, 0, tzinfo=TZ), days=(6,), name="weekly_recap")

    app.run_polling()

if __name__ == "__main__":
    main()
