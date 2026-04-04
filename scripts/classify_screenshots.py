#!/usr/bin/env python3
"""
Classify screenshots using Claude Vision and copy matches to the flashback bot.

Usage:
    python scripts/classify_screenshots.py /path/to/exported/photos
    python scripts/classify_screenshots.py /path/to/exported/photos --output screenshots
    python scripts/classify_screenshots.py /path/to/exported/photos --dry-run
    python scripts/classify_screenshots.py /path/to/exported/photos --resume

Requires ANTHROPIC_API_KEY env var.
"""

import argparse
import base64
import json
import mimetypes
import shutil
import sys
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Missing dependency: pip install anthropic")
    sys.exit(1)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heif"}

CLASSIFY_PROMPT = """\
Look at this screenshot and decide if it belongs in ONE of these categories:

1. **insight** — A tweet, post, article excerpt, or note containing wisdom about inner work, emotions, personal growth, meditation, relationships, or how to live life well.
2. **funny_meme** — A funny meme or comic that would make someone laugh or smile.
3. **moving_exchange** — A funny or moving text/chat exchange with a friend.
4. **no** — Anything else (app UI, receipts, navigation, notifications, random screenshots, etc.)

Respond with ONLY a JSON object, no other text:
{"category": "insight|funny_meme|moving_exchange|no", "confidence": "high|medium|low"}
"""

PROGRESS_FILE = ".classify_progress.json"


def load_progress(output_dir: Path) -> dict:
    path = output_dir / PROGRESS_FILE
    if path.exists():
        return json.loads(path.read_text())
    return {"classified": {}}


def save_progress(output_dir: Path, progress: dict):
    path = output_dir / PROGRESS_FILE
    path.write_text(json.dumps(progress, indent=2))


def get_images(source_dir: Path) -> list[Path]:
    files = []
    for f in sorted(source_dir.rglob("*")):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
            files.append(f)
    return files


def encode_image(path: Path) -> tuple[str, str]:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    # Claude API supports these media types
    if mime not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        mime = "image/jpeg"
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return mime, data


def classify_image(client: anthropic.Anthropic, path: Path) -> dict:
    mime, data = encode_image(path)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": data,
                        },
                    },
                    {"type": "text", "text": CLASSIFY_PROMPT},
                ],
            }
        ],
    )
    text = resp.content[0].text.strip()
    # Parse JSON from response
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"category": "no", "confidence": "low"}


def main():
    parser = argparse.ArgumentParser(description="Classify screenshots for flashback bot")
    parser.add_argument("source", type=Path, help="Directory of exported photos to classify")
    parser.add_argument(
        "--output",
        type=str,
        default="screenshots",
        help="Folder name in DATA_DIR to copy matches to (default: screenshots)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Classify but don't copy files")
    parser.add_argument("--resume", action="store_true", help="Resume from where you left off")
    parser.add_argument(
        "--min-confidence",
        choices=["low", "medium", "high"],
        default="low",
        help="Minimum confidence to accept (default: low)",
    )
    parser.add_argument("--data-dir", type=Path, default=None, help="Override DATA_DIR")
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"Error: {args.source} is not a directory")
        sys.exit(1)

    # Determine output directory
    data_dir = args.data_dir or Path(__file__).resolve().parent.parent
    output_dir = data_dir / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    client = anthropic.Anthropic()
    images = get_images(args.source)
    print(f"Found {len(images)} images in {args.source}")

    # Load progress for resume
    progress = load_progress(output_dir) if args.resume else {"classified": {}}
    already_done = set(progress["classified"].keys())

    if args.resume and already_done:
        print(f"Resuming — {len(already_done)} already classified, skipping those")

    confidence_levels = {"high": 3, "medium": 2, "low": 1}
    min_conf = confidence_levels[args.min_confidence]

    stats = {"insight": 0, "funny_meme": 0, "moving_exchange": 0, "no": 0, "error": 0}
    copied = 0

    for i, img in enumerate(images):
        key = str(img.relative_to(args.source))

        if key in already_done:
            # Count previous results in stats
            prev = progress["classified"][key]
            stats[prev.get("category", "no")] = stats.get(prev.get("category", "no"), 0) + 1
            if prev.get("category", "no") != "no":
                copied += 1
            continue

        print(f"[{i+1}/{len(images)}] {img.name} ... ", end="", flush=True)

        try:
            result = classify_image(client, img)
            category = result.get("category", "no")
            confidence = result.get("confidence", "low")
            conf_level = confidence_levels.get(confidence, 1)

            stats[category] = stats.get(category, 0) + 1
            progress["classified"][key] = result

            if category != "no" and conf_level >= min_conf:
                print(f"YES ({category}, {confidence})")
                if not args.dry_run:
                    dest = output_dir / img.name
                    # Avoid name collisions
                    if dest.exists():
                        dest = output_dir / f"{img.stem}_{i}{img.suffix}"
                    shutil.copy2(img, dest)
                    copied += 1
            else:
                print(f"no ({category}, {confidence})")

            save_progress(output_dir, progress)

        except anthropic.RateLimitError:
            print("rate limited, waiting 30s...")
            time.sleep(30)
            continue
        except Exception as e:
            print(f"error: {e}")
            stats["error"] += 1

    print(f"\n--- Done ---")
    print(f"Total: {len(images)}")
    print(f"  Insights:   {stats['insight']}")
    print(f"  Memes:      {stats['funny_meme']}")
    print(f"  Exchanges:  {stats['moving_exchange']}")
    print(f"  Skipped:    {stats['no']}")
    print(f"  Errors:     {stats['error']}")
    if not args.dry_run:
        print(f"\nCopied {copied} files to {output_dir}")
    else:
        print(f"\n(dry run — {copied} files would be copied to {output_dir})")


if __name__ == "__main__":
    main()
