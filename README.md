# Flashback Bot

Telegram bot that sends you a random photo once a day at a surprise time (between 8am and midnight).

Photos are served from a local `photos/` directory — just drop image files in there and deploy.

## Setup

### Telegram

1. Message [@BotFather](https://t.me/BotFather), create a bot, copy the token
2. Message the bot `/start` to get your chat ID

### Environment

Copy `.env.example` to `.env` and fill in:

- `TELEGRAM_BOT_TOKEN` — from BotFather
- `TELEGRAM_CHAT_ID` — from `/start`
- `TZ` — your timezone (e.g. `Europe/Berlin`)

### Photos

Add images (`.jpg`, `.jpeg`, `.png`, `.heif`, `.webp`) to the `photos/` directory.

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m flashback_bot.main
```

## Commands

- `/flashback` — sends a random photo immediately
- `/count` — shows how many photos are in the pool

## Deploying to Railway

```bash
railway up --detach
```

Photos are baked into the Docker image. To update the pool, add/remove photos locally then redeploy.

## Project structure

```
flashback_bot/
  main.py     — bot commands, scheduling, entry point
photos/       — image files to pick from
```
