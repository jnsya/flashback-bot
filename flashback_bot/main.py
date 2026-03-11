import logging
import os
import random
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("flashback")

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
AUTHORIZED_USER_ID = int(CHAT_ID)
TIMEZONE = os.environ.get("TZ", "Europe/Berlin")

BASE_DIR = Path(__file__).parent.parent
PHOTOS_DIR = Path(os.environ.get("PHOTOS_DIR", BASE_DIR / "photos"))
REMINDERS_DIR = Path(os.environ.get("REMINDERS_DIR", BASE_DIR / "reminders"))

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heif", ".webp", ".gif"}
TEXT_EXTS = {".txt", ".md"}


# ── Auth ──────────────────────────────────────────────────────────────

def authorized(func):
    """Decorator that silently ignores commands from unauthorized users."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and update.effective_user.id == AUTHORIZED_USER_ID:
            return await func(update, context)
        log.warning(
            "Unauthorized access attempt from user %s (%s)",
            update.effective_user.id if update.effective_user else "unknown",
            update.effective_user.username if update.effective_user else "unknown",
        )
    return wrapper


# ── Helpers ───────────────────────────────────────────────────────────

def _list_files(directory: Path, extensions: set[str]) -> list[Path]:
    if not directory.exists():
        return []
    return [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in extensions
    ]


def get_random_photo() -> Path | None:
    photos = _list_files(PHOTOS_DIR, IMAGE_EXTS)
    return random.choice(photos) if photos else None


def get_random_reminder() -> Path | None:
    items = _list_files(REMINDERS_DIR, IMAGE_EXTS | TEXT_EXTS)
    return random.choice(items) if items else None


def get_photo_count() -> int:
    return len(_list_files(PHOTOS_DIR, IMAGE_EXTS))


def get_reminder_count() -> int:
    return len(_list_files(REMINDERS_DIR, IMAGE_EXTS | TEXT_EXTS))


# ── Last-sent tracking ────────────────────────────────────────────────

# Tracks the most recently sent item per type so /remove can delete it.
_last_sent: dict[str, Path | None] = {"flashback": None, "reminder": None}


# ── Sending ───────────────────────────────────────────────────────────

async def send_flashback(bot: Bot, chat_id: str):
    photo_path = get_random_photo()
    if photo_path is None:
        await bot.send_message(chat_id=chat_id, text="No photos in the pool!")
        return
    with open(photo_path, "rb") as f:
        await bot.send_photo(
            chat_id=chat_id, photo=f,
            caption="*Flashback* \u2728", parse_mode="Markdown",
        )
    _last_sent["flashback"] = photo_path
    log.info("Sent flashback: %s", photo_path.name)


async def send_reminder(bot: Bot, chat_id: str):
    item = get_random_reminder()
    if item is None:
        return  # silently skip if no reminders yet
    if item.suffix.lower() in TEXT_EXTS:
        text = item.read_text(encoding="utf-8").strip()
        if text:
            await bot.send_message(
                chat_id=chat_id, text=text, parse_mode="Markdown",
            )
    else:
        with open(item, "rb") as f:
            await bot.send_photo(chat_id=chat_id, photo=f)
    _last_sent["reminder"] = item
    log.info("Sent reminder: %s", item.name)


# ── Command handlers ─────────────────────────────────────────────────

@authorized
async def cmd_flashback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /flashback — send a random photo now."""
    await send_flashback(context.bot, str(update.effective_chat.id))


@authorized
async def cmd_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reminder — send a random reminder now."""
    item = get_random_reminder()
    if item is None:
        await update.message.reply_text("No reminders yet! Add files to the reminders/ folder.")
        return
    await send_reminder(context.bot, str(update.effective_chat.id))


@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_photos = get_photo_count()
    total_reminders = get_reminder_count()
    await update.message.reply_text(
        f"Hey! I'm Flashback \u2728\n\n"
        f"I'll send you a random photo at a surprise time each day "
        f"between 8am and midnight ({TIMEZONE}).\n\n"
        f"I also send random reminders from your collection "
        f"on a separate schedule.\n\n"
        f"Commands:\n"
        f"/flashback — random photo now\n"
        f"/reminder — random reminder now\n"
        f"/remove — delete the last sent item from the pool\n"
        f"/count — see pool sizes\n\n"
        f"Photos: {total_photos} · Reminders: {total_reminders}",
    )


@authorized
async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remove — delete the last sent flashback or reminder from the pool."""
    # Check which type was sent most recently
    fb = _last_sent.get("flashback")
    rm = _last_sent.get("reminder")

    # If the user replies to a specific message, we can't match it to a file,
    # so just remove whichever was sent last. User can specify /remove flashback
    # or /remove reminder to be explicit.
    args = context.args
    if args and args[0].lower() in ("flashback", "photo"):
        target, kind = fb, "flashback"
    elif args and args[0].lower() == "reminder":
        target, kind = rm, "reminder"
    else:
        # Remove whichever was sent most recently (no arg given)
        target, kind = fb, "flashback"
        if rm and (not fb or (rm.stat().st_atime if rm.exists() else 0) > (fb.stat().st_atime if fb.exists() else 0)):
            target, kind = rm, "reminder"

    if target is None:
        await update.message.reply_text("Nothing to remove — no recent flashback or reminder.")
        return

    if not target.exists():
        _last_sent[kind] = None
        await update.message.reply_text("Already removed.")
        return

    name = target.name
    target.unlink()
    _last_sent[kind] = None
    await update.message.reply_text(f"Removed {kind}: {name}")
    log.info("Removed %s: %s", kind, name)


@authorized
async def cmd_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_photos = get_photo_count()
    total_reminders = get_reminder_count()
    await update.message.reply_text(
        f"Photos: {total_photos}\nReminders: {total_reminders}"
    )


# ── Scheduling ────────────────────────────────────────────────────────

def _random_time_today_or_tomorrow(tz, hour_start, hour_end):
    """Return a random datetime between hour_start:00 and hour_end:59, today or tomorrow."""
    now = datetime.now(tz)
    hour = random.randint(hour_start, hour_end)
    minute = random.randint(0, 59)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def schedule_next_flashback(scheduler, bot, chat_id):
    """Schedule the next flashback at a random time between 8:00 and 23:59."""
    tz = pytz.timezone(TIMEZONE)
    run_date = _random_time_today_or_tomorrow(tz, 8, 23)

    async def flashback_and_reschedule():
        await send_flashback(bot, chat_id)
        schedule_next_flashback(scheduler, bot, chat_id)

    scheduler.add_job(
        flashback_and_reschedule, "date", run_date=run_date,
        id="next_flashback", replace_existing=True,
    )
    log.info("Next flashback scheduled at %s", run_date.strftime("%Y-%m-%d %H:%M %Z"))


def schedule_next_reminder(scheduler, bot, chat_id):
    """Schedule the next reminder at a random time between 9:00 and 22:59."""
    tz = pytz.timezone(TIMEZONE)

    # Skip scheduling if no reminders exist
    if get_reminder_count() == 0:
        log.info("No reminders in pool, will check again tomorrow")
        # Check again tomorrow at 9am
        now = datetime.now(tz)
        check_time = (now + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0,
        )
        scheduler.add_job(
            lambda: schedule_next_reminder(scheduler, bot, chat_id),
            "date", run_date=check_time,
            id="next_reminder", replace_existing=True,
        )
        return

    run_date = _random_time_today_or_tomorrow(tz, 9, 22)

    async def reminder_and_reschedule():
        await send_reminder(bot, chat_id)
        schedule_next_reminder(scheduler, bot, chat_id)

    scheduler.add_job(
        reminder_and_reschedule, "date", run_date=run_date,
        id="next_reminder", replace_existing=True,
    )
    log.info("Next reminder scheduled at %s", run_date.strftime("%Y-%m-%d %H:%M %Z"))


# ── App lifecycle ─────────────────────────────────────────────────────

async def post_init(app: Application):
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.start()
    schedule_next_flashback(scheduler, app.bot, CHAT_ID)
    schedule_next_reminder(scheduler, app.bot, CHAT_ID)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("flashback", cmd_flashback))
    app.add_handler(CommandHandler("reminder", cmd_reminder))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("count", cmd_count))

    app.run_polling()


if __name__ == "__main__":
    main()
