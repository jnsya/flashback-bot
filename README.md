# Flashback Bot

Telegram bot that sends you a random photo once a day at a surprise time (between 8am and midnight). Also sends random reminders (text, images, memes, poems) on a separate schedule.

Only responds to the authorized user (matched via `TELEGRAM_CHAT_ID`).

## Setup

### Telegram

1. Message [@BotFather](https://t.me/BotFather), create a bot, copy the token
2. Message the bot `/start` to get your chat ID

### Environment

Copy `.env.example` to `.env` and fill in:

- `TELEGRAM_BOT_TOKEN` — from BotFather
- `TELEGRAM_CHAT_ID` — your chat ID (also used for authorization)
- `TZ` — your timezone (e.g. `Europe/Berlin`)

### Content

- `photos/` — image files (`.jpg`, `.jpeg`, `.png`, `.heif`, `.webp`, `.gif`) for daily flashbacks
- `reminders/` — images or text files (`.txt`, `.md`) for random reminders

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m flashback_bot.main
```

## Commands

- `/flashback` — sends a random photo immediately
- `/reminder` — sends a random reminder immediately
- `/count` — shows how many photos and reminders are in the pool

## Deploying to Railway

The bot runs on Railway with a persistent volume at `/data` for photos and reminders.

**First deploy (with photos):**

```bash
railway init
railway link
railway volume add --mount-path /data
railway variable set TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... TZ=Europe/Berlin PHOTOS_DIR=/data/photos REMINDERS_DIR=/data/reminders
railway up --no-gitignore
```

`--no-gitignore` includes `photos/` and `reminders/` in the build. The entrypoint copies them to the persistent volume on startup.

**Code-only deploys:**

```bash
railway up
```

**Adding new photos or reminders:**

Drop files into `photos/` or `reminders/` locally, then:

```bash
railway up --no-gitignore
```

Existing files on the volume are not overwritten.

## Project structure

```
flashback_bot/
  main.py       — bot commands, scheduling, auth, entry point
photos/         — image files for flashbacks (gitignored)
reminders/      — text/image files for reminders (gitignored)
entrypoint.sh   — syncs seed data to Railway volume on startup
```
