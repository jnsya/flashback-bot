#!/bin/sh
# Sync any bundled seed data to the volume (skips files that already exist)
for dir in photos reminders; do
    if [ -d "/app/_seed_$dir" ] && [ -d "/data/$dir" ]; then
        cp -n /app/_seed_$dir/* /data/$dir/ 2>/dev/null
        echo "Synced $dir: $(ls /data/$dir/ | wc -l) files"
    fi
done
exec python -m flashback_bot.main
