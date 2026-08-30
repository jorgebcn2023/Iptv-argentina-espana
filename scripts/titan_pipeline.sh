#!/usr/bin/env bash
set -euo pipefail

# TITAN v2 isolated pipeline. Production/main is never modified here.
python discover_reddit.py
python main.py
python resolve_youtube.py

# Deduplicate the complete generated playlist by normalized URL.
python scripts/titan_dedupe.py playlist-full.m3u playlist-full-deduped.m3u
mv playlist-full-deduped.m3u playlist-full.m3u

# Static quality gates.
python scripts/titan_qc.py playlist.m3u
python scripts/titan_qc.py playlist-full.m3u

python - <<'PY'
from pathlib import Path

def entries(p):
    return sum(1 for line in Path(p).read_text(encoding='utf-8', errors='replace').splitlines() if line.startswith('#EXTINF'))
print(f"TITAN stable={entries('playlist.m3u')} full_deduped={entries('playlist-full.m3u')} quarantine={entries('playlist-quarantine.m3u')}")
PY
