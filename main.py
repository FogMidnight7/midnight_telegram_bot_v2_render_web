import os
from datetime import time
from zoneinfo import ZoneInfo
from telegram.ext import ApplicationBuilder, CommandHandler

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Tallinn"))

async def start(update, context):
    await update.message.reply_text("Bot is alive.")

async def daily_affirmation(context):
    chat_id = int(os.environ.get("ADMIN_CHAT_ID", context.job.chat_id or 0))
    if chat_id:
        await context.bot.send_message(chat_id, "Affirmation…")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # handlers
    app.add_handler(CommandHandler("start", start))

    # job queue (this is NOT None in v20)
    jq = app.job_queue
    jq.run_daily(daily_affirmation, time=time(6, 0, tzinfo=TZ), name="daily_aff")

    app.run_polling()

if __name__ == "__main__":
    main()
