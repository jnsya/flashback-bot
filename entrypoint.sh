#!/bin/sh
# Sync any bundled seed data to the volume (skips files that already exist)
for seed_dir in /app/_seed_*/; do
    [ -d "$seed_dir" ] || continue
    name=$(basename "$seed_dir" | sed 's/^_seed_//')
    mkdir -p "/data/$name"
    cp -n "$seed_dir"* "/data/$name/" 2>/dev/null
    echo "Synced $name: $(ls /data/$name/ | wc -l) files"
done
exec python -m flashback_bot.main
