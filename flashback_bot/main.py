import logging
import os
import random
import tomllib
from dataclasses import dataclass, field
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
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heif", ".webp", ".gif"}
TEXT_EXTS = {".txt", ".md"}
ALL_EXTS = IMAGE_EXTS | TEXT_EXTS


# ── Config ───────────────────────────────────────────────────────────

@dataclass
class FolderConfig:
    name: str
    path: Path
    caption: str = ""
    hour_start: int = 10
    hour_end: int = 22
    days: set[int] | None = None  # None = every day; 0=Monday, 6=Sunday
    file_types: set[str] = field(default_factory=lambda: ALL_EXTS.copy())
    command: str | None = None


def discover_folders(data_dir: Path, config_path: Path | None = None) -> dict[str, FolderConfig]:
    """Scan data_dir for subdirectories; merge with folders.toml if present."""
    config = {}
    defaults = {}

    if config_path and config_path.exists():
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
        defaults = raw.get("defaults", {})
        config = raw.get("folders", {})

    # Collect folder names from both filesystem and config
    folder_names: set[str] = set()
    if data_dir.exists():
        for p in data_dir.iterdir():
            if p.is_dir() and not p.name.startswith((".", "_")):
                folder_names.add(p.name)
    for name in config:
        folder_names.add(name)

    folders: dict[str, FolderConfig] = {}
    for name in sorted(folder_names):
        folder_dir = data_dir / name
        folder_dir.mkdir(parents=True, exist_ok=True)

        fc = config.get(name, {})
        days_raw = fc.get("days", defaults.get("days"))
        days = set(days_raw) if days_raw is not None else None

        folders[name] = FolderConfig(
            name=name,
            path=folder_dir,
            caption=fc.get("caption", defaults.get("caption", "")),
            hour_start=fc.get("hour_start", defaults.get("hour_start", 10)),
            hour_end=fc.get("hour_end", defaults.get("hour_end", 22)),
            days=days,
            command=fc.get("command"),
        )

    return folders


# ── Auth ─────────────────────────────────────────────────────────────

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


# ── Helpers ──────────────────────────────────────────────────────────

def _list_files(directory: Path, extensions: set[str]) -> list[Path]:
    if not directory.exists():
        return []
    return [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in extensions
    ]


def _get_random_file(folder: FolderConfig) -> Path | None:
    files = _list_files(folder.path, folder.file_types)
    return random.choice(files) if files else None


def _get_file_count(folder: FolderConfig) -> int:
    return len(_list_files(folder.path, folder.file_types))


# ── Last-sent tracking ──────────────────────────────────────────────

_last_sent: dict[str, Path | None] = {}


# ── Sending ─────────────────────────────────────────────────────────

async def send_from_folder(bot: Bot, chat_id: str, folder: FolderConfig):
    """Send a random file from a folder. Handles text and image files."""
    item = _get_random_file(folder)
    if item is None:
        return

    if item.suffix.lower() in TEXT_EXTS:
        text = item.read_text(encoding="utf-8").strip()
        if text:
            await bot.send_message(
                chat_id=chat_id, text=text, parse_mode="Markdown",
            )
    else:
        with open(item, "rb") as f:
            kwargs = {}
            if folder.caption:
                kwargs["caption"] = folder.caption
                kwargs["parse_mode"] = "Markdown"
            await bot.send_photo(chat_id=chat_id, photo=f, **kwargs)

    _last_sent[folder.name] = item
    log.info("Sent %s: %s", folder.name, item.name)


# ── Scheduling ──────────────────────────────────────────────────────

def _random_time_next_valid_day(tz, hour_start, hour_end, days: set[int] | None, *, allow_today: bool):
    """Return a random datetime on the next valid day within the hour window."""
    now = datetime.now(tz)

    if allow_today:
        hour = random.randint(hour_start, hour_end)
        minute = random.randint(0, 59)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > now and (days is None or now.weekday() in days):
            return candidate

    # Search forward up to 8 days to find a valid day
    for offset in range(1, 9):
        day = now + timedelta(days=offset)
        if days is None or day.weekday() in days:
            hour = random.randint(hour_start, hour_end)
            minute = random.randint(0, 59)
            return day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Fallback (shouldn't happen unless days is empty)
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=hour_start, minute=0, second=0, microsecond=0)


def schedule_next(scheduler, bot, chat_id, folder: FolderConfig, *, allow_today=False):
    """Schedule the next send for a folder at a random time."""
    tz = pytz.timezone(TIMEZONE)
    job_id = f"next_{folder.name}"

    # If folder is empty, check again tomorrow
    if _get_file_count(folder) == 0:
        log.info("No files in %s, will check again tomorrow", folder.name)
        now = datetime.now(tz)
        check_time = (now + timedelta(days=1)).replace(
            hour=folder.hour_start, minute=0, second=0, microsecond=0,
        )
        scheduler.add_job(
            lambda _f=folder: schedule_next(scheduler, bot, chat_id, _f, allow_today=True),
            "date", run_date=check_time,
            id=job_id, replace_existing=True,
        )
        return

    run_date = _random_time_next_valid_day(
        tz, folder.hour_start, folder.hour_end, folder.days, allow_today=allow_today,
    )

    async def send_and_reschedule(_f=folder):
        try:
            await send_from_folder(bot, chat_id, _f)
        except Exception:
            log.exception("Failed to send from %s, will retry next cycle", _f.name)
        schedule_next(scheduler, bot, chat_id, _f)

    scheduler.add_job(
        send_and_reschedule, "date", run_date=run_date,
        id=job_id, replace_existing=True,
    )
    log.info("Next %s scheduled at %s", folder.name, run_date.strftime("%Y-%m-%d %H:%M %Z"))


# ── Command handlers ────────────────────────────────────────────────

def _make_folder_command(folder: FolderConfig):
    """Create a command handler for a folder."""
    @authorized
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE, _f=folder):
        item = _get_random_file(_f)
        if item is None:
            await update.message.reply_text(
                f"No files in {_f.name}/ yet! Add files to the folder."
            )
            return
        await send_from_folder(context.bot, str(update.effective_chat.id), _f)
    return handler


# These will be populated in main()
_folders: dict[str, FolderConfig] = {}


@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [f"Hey! I'm Flashback \u2728\n"]
    lines.append(
        "I send random content from your folders at surprise times each day "
        f"({TIMEZONE}).\n"
    )
    lines.append("Commands:")
    for folder in _folders.values():
        if folder.command:
            count = _get_file_count(folder)
            lines.append(f"/{folder.command} — random {folder.name} ({count} files)")
    lines.append("/remove [folder] — delete the last sent item from a folder")
    lines.append("/count — see all folder sizes")
    await update.message.reply_text("\n".join(lines))


@authorized
async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remove [folder_name] — delete the last sent item."""
    args = context.args

    if args:
        # Try to match arg to a folder name or command name
        key = args[0].lower()
        target_folder = None
        for folder in _folders.values():
            if key in (folder.name, folder.command):
                target_folder = folder
                break
        if target_folder is None:
            await update.message.reply_text(
                f"Unknown folder: {key}\nAvailable: {', '.join(_folders.keys())}"
            )
            return
        target = _last_sent.get(target_folder.name)
        kind = target_folder.name
    else:
        # No arg: find the most recently sent item across all folders
        target, kind = None, None
        best_atime = 0
        for name, path in _last_sent.items():
            if path and path.exists():
                atime = path.stat().st_atime
                if atime > best_atime:
                    best_atime = atime
                    target, kind = path, name
        if target is None:
            # Fall back to any non-None entry
            for name, path in _last_sent.items():
                if path is not None:
                    target, kind = path, name
                    break

    if target is None:
        await update.message.reply_text("Nothing to remove — no recently sent items.")
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
    lines = []
    for folder in _folders.values():
        count = _get_file_count(folder)
        lines.append(f"{folder.name}: {count}")
    await update.message.reply_text("\n".join(lines))


# ── App lifecycle ────────────────────────────────────────────────────

async def post_init(app: Application):
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.start()
    app.bot_data["scheduler"] = scheduler  # prevent garbage collection
    for folder in _folders.values():
        schedule_next(scheduler, app.bot, CHAT_ID, folder, allow_today=True)


def main():
    global _folders

    config_path = BASE_DIR / "folders.toml"
    _folders = discover_folders(DATA_DIR, config_path)
    log.info("Discovered folders: %s", list(_folders.keys()))

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("count", cmd_count))

    # Dynamic command registration
    for folder in _folders.values():
        if folder.command:
            app.add_handler(CommandHandler(folder.command, _make_folder_command(folder)))

    app.run_polling()


if __name__ == "__main__":
    main()
