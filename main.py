#!/usr/bin/env python3
import os, json, logging, asyncio
from datetime import datetime, time
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from aiohttp import web

PORT = int(os.getenv("PORT", "10000"))
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Tallinn"))
SUBS_FILE = os.getenv("SUBSCRIBERS_FILE", "subscribers.json")
QUIET_HOUR_END = time(6, 0)
QUIET_HOUR_START = time(21, 0)

def load_messages():
    import yaml
    with open("messages.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("affirmations", []), data.get("motivations", []), data.get("weekly", [])

AFFIRMATIONS, MOTIVATIONS, WEEKLY = [], [], []

def load_subscribers():
    if not os.path.exists(SUBS_FILE):
        return {"chats": {}}
    with open(SUBS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_subscribers(data):
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def is_quiet_hours(now=None):
    now = now or datetime.now(TZ).time()
    return (QUIET_HOUR_START <= now or now < QUIET_HOUR_END)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subs = load_subscribers()
    subs["chats"].setdefault(str(chat_id), {"affirmation": True, "motivation": True, "weekly": True})
    save_subscribers(subs)
    text = ("🌑 **Midnight Fogwalker** online.\n\n"
            "You are subscribed:\n"
            "• Daily **affirmation** 06:00\n"
            "• Daily **motivation** 13:00\n"
            "• **Weekly recap** Sunday 19:00\n\n"
            "Quiet hours after 21:00. /unsubscribe to stop, /status to view.")
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("Commands:\n"
            "/start — subscribe\n"
            "/affirmation — send one now\n"
            "/motivate — send one now\n"
            "/subscribe — enable all\n"
            "/unsubscribe — stop all\n"
            "/status — current settings")
    await update.effective_message.reply_text(text)

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subs = load_subscribers()
    subs["chats"][chat_id] = {"affirmation": True, "motivation": True, "weekly": True}
    save_subscribers(subs)
    await update.effective_message.reply_text("Subscribed to affirmation, motivation, and weekly.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subs = load_subscribers()
    if chat_id in subs["chats"]:
        subs["chats"].pop(chat_id)
        save_subscribers(subs)
    await update.effective_message.reply_text("Unsubscribed. Use /start anytime.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subs = load_subscribers()
    s = subs["chats"].get(chat_id)
    if not s:
        await update.effective_message.reply_text("Not subscribed. Use /start.")
        return
    await update.effective_message.reply_text(
        f"Subscriptions:\n- Affirmation: {s.get('affirmation', False)}\n- Motivation: {s.get('motivation', False)}\n- Weekly: {s.get('weekly', False)}"
    )

def get_next(items, index_file):
    idx = 0
    if os.path.exists(index_file):
        try:
            with open(index_file, "r") as f:
                idx = int(f.read().strip())
        except Exception:
            idx = 0
    if not items:
        return "…(no content configured yet)"
    msg = items[idx % len(items)]
    with open(index_file, "w") as f:
        f.write(str((idx + 1) % len(items)))
    return msg

async def affirmation_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_quiet_hours():
        await update.effective_message.reply_text("Quiet hours. Back after 06:00.")
        return
    msg = get_next(AFFIRMATIONS, "affirmations_index.json")
    await update.effective_message.reply_text(msg)

async def motivate_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_quiet_hours():
        await update.effective_message.reply_text("Quiet hours. Back after 06:00.")
        return
    msg = get_next(MOTIVATIONS, "motivations_index.json")
    await update.effective_message.reply_text(msg)

async def send_affirmations(app):
    if is_quiet_hours():
        return
    subs = load_subscribers()
    msg = get_next(AFFIRMATIONS, "affirmations_index.json")
    for chat_id in list(subs["chats"].keys()):
        try:
            await app.bot.send_message(chat_id=int(chat_id), text=msg)
        except Exception as e:
            logging.warning(f"Affirmation failed for {chat_id}: {e}")

async def send_motivations(app):
    if is_quiet_hours():
        return
    subs = load_subscribers()
    msg = get_next(MOTIVATIONS, "motivations_index.json")
    for chat_id in list(subs["chats"].keys()):
        try:
            await app.bot.send_message(chat_id=int(chat_id), text=msg)
        except Exception as e:
            logging.warning(f"Motivation failed for {chat_id}: {e}")

async def send_weekly(app):
    if is_quiet_hours():
        return
    subs = load_subscribers()
    msg = get_next(WEEKLY, "weekly_index.json")
    for chat_id in list(subs["chats"].keys()):
        try:
            await app.bot.send_message(chat_id=int(chat_id), text=msg, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logging.warning(f"Weekly failed for {chat_id}: {e}")

def schedule_jobs(app):
    jq = app.job_queue
    jq.run_daily(lambda ctx: app.create_task(send_affirmations(app)), time(hour=6, minute=0, tzinfo=TZ), name="affirmations")
    jq.run_daily(lambda ctx: app.create_task(send_motivations(app)), time(hour=13, minute=0, tzinfo=TZ), name="motivations")
    jq.run_daily(lambda ctx: app.create_task(send_weekly(app)), time(hour=19, minute=0, tzinfo=TZ), days=(6,), name="weekly")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Unknown command. Try /help.")

def require_token():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
    return token

async def run_bot_and_web():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    global AFFIRMATIONS, MOTIVATIONS, WEEKLY
    AFFIRMATIONS, MOTIVATIONS, WEEKLY = load_messages()

    token = require_token()
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("affirmation", affirmation_now))
    app.add_handler(CommandHandler("motivate", motivate_now))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    schedule_jobs(app)

    async def handle_root(request):
        return web.Response(text="Midnight Fogwalker bot is running.", content_type="text/plain")

    async def handle_health(request):
        return web.json_response({"status": "ok", "time": datetime.now(TZ).isoformat()})

    webapp = web.Application()
    webapp.add_routes([web.get("/", handle_root), web.get("/health", handle_health)])

    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)

    tg_task = asyncio.create_task(app.run_polling(close_loop=False))
    web_task = asyncio.create_task(site.start())

    await asyncio.gather(tg_task, web_task)

if __name__ == "__main__":
    try:
        asyncio.run(run_bot_and_web())
    except KeyboardInterrupt:
        pass
