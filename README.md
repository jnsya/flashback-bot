# Flashback Bot

Telegram bot that sends you random content from configurable folders at surprise times throughout the day. Only responds to the authorized user (matched via `TELEGRAM_CHAT_ID`).

## Deploy to Railway

Requires a persistent volume at `/data` and three env vars.

**First-time setup:**

```bash
railway init
railway link
railway volume add --mount-path /data
railway variable set TELEGRAM_BOT_TOKEN=<token> TELEGRAM_CHAT_ID=<chat_id> TZ=Europe/Berlin DATA_DIR=/data
railway up --no-gitignore
```

`--no-gitignore` bundles your content folders into the build. On startup the entrypoint syncs them to the persistent volume (won't overwrite existing files).

**Subsequent deploys (code/config only):**

```bash
railway up
```

**Adding new content to Railway:**

```bash
railway up --no-gitignore
```

**Migrating from the old env vars:** If you previously had `PHOTOS_DIR` and `REMINDERS_DIR` set, replace them with a single `DATA_DIR=/data` and redeploy.

## Content folders

Any subdirectory under `DATA_DIR` is automatically discovered as a content folder. The bot sends one random file per folder per day.

Supported file types: `.jpg`, `.jpeg`, `.png`, `.heif`, `.webp`, `.gif`, `.txt`, `.md`

To add a new folder, just create it and add files:

```bash
mkdir quotes
echo "Stay hungry, stay foolish." > quotes/quote1.txt
```

Restart the bot (or redeploy) and it picks up the new folder automatically.

## Configuration

Optionally configure folders in `folders.toml`:

```toml
[defaults]
caption = ""
hour_start = 10
hour_end = 22
# days = [0,1,2,3,4,5,6]  # 0=Monday, 6=Sunday. Default: all days.

[folders.photos]
caption = "*Flashback* ✨"
command = "flashback"

[folders.reminders]
command = "reminder"

[folders.memes]
caption = "😂"
command = "meme"
days = [0, 2, 4]  # Mon/Wed/Fri only
```

| Field | Description | Default |
|-------|-------------|---------|
| `caption` | Markdown caption for image messages | `""` (none) |
| `hour_start` | Earliest hour to send (0–23) | `10` |
| `hour_end` | Latest hour to send (0–23) | `22` |
| `days` | Weekdays to send on (0=Mon, 6=Sun) | all days |
| `command` | Register a `/command` for on-demand sends | none |

`[defaults]` applies to all folders. Per-folder sections override defaults. Folders without a config section get defaults only. Folders listed in config that don't exist on disk are created automatically.

## Commands

Registered dynamically from `folders.toml`:

- `/flashback` — sends a random photo now
- `/reminder` — sends a random reminder now
- `/remove [folder]` — deletes the last sent item (e.g. `/remove photos`, or no arg for most recent)
- `/count` — file counts for all folders

## Running locally

```bash
cp .env.example .env   # fill in token + chat ID
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m flashback_bot.main
```

`DATA_DIR` defaults to the project root locally, so `photos/`, `reminders/`, etc. are read from the repo directory.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | yes | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | yes | Your chat ID (also used for auth) |
| `TZ` | no | Timezone (default: `Europe/Berlin`) |
| `DATA_DIR` | no | Content directory (default: project root locally, `/data` on Railway) |

## Project structure

```
flashback_bot/
  main.py       — bot logic, folder discovery, scheduling, commands
folders.toml    — optional per-folder configuration
photos/         — image files for flashbacks (gitignored)
reminders/      — text/image files for reminders (gitignored)
entrypoint.sh   — syncs seed content to Railway volume on startup
Dockerfile      — production build
```
