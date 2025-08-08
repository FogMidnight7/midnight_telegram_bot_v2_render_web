# Midnight Fogwalker Telegram Bot (v2) — Render Web Service

Runs on Render's free **Web Service** by exposing a tiny web server alongside the Telegram bot.

## Render deploy
1) Push files to a public GitHub repo.
2) In Render: New → **Web Service** (not Background Worker).
3) Connect repo, EU (Frankfurt).
4) Build Command: `pip install -r requirements.txt`
5) Start Command: `python main.py`
6) Environment:
   - TELEGRAM_BOT_TOKEN = 8032091198:AAFFKFEg3LTIXgwmSoP-zrDq_4W9ltWEV5o
   - TIMEZONE = Europe/Tallinn
   - SUBSCRIBERS_FILE = subscribers.json
7) Deploy. Check `/health` path for a JSON status.
